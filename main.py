import os
import json
import logging
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("launchoutreach-backend")

# Load environment variables from .env file if present
load_dotenv()

app = FastAPI(
    title="LaunchOutreach AI Backend",
    description="Core automation and AI engine for YC sourcing and LinkedIn outreach.",
    version="1.0.0"
)

# CORS Setup: Allow all origins as requested so frontend (Vercel, Localhost) can communicate
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Google GenAI client safely
def get_genai_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY environment variable is not set.")
        # If API key is missing, Client() will look for the environment variable.
        # We try to initialize anyway. If it fails, let's catch it in endpoints.
    try:
        return genai.Client()
    except Exception as e:
        logger.error(f"Error initializing Google GenAI Client: {e}")
        raise HTTPException(
            status_code=500,
            detail="Google GenAI Client initialization failed. Check your GEMINI_API_KEY."
        )

# Endpoint 1: GET /ping (crucial to keep Render server awake)
@app.get("/ping")
def ping():
    return {"status": "alive"}

# Endpoint 2: POST /api/generate-caption
@app.post("/api/generate-caption")
async def generate_caption(file: UploadFile = File(...)):
    # 1. Verify file upload
    if not file:
        raise HTTPException(status_code=400, detail="No image file provided.")
    
    # Read file bytes
    try:
        contents = await file.read()
    except Exception as e:
        logger.error(f"Failed to read upload file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read uploaded file: {e}")

    # Determine MIME type
    mime_type = file.content_type or "image/png"
    
    # 2. Get GenAI client
    client = get_genai_client()

    prompt_text = "Write a professional, technical LinkedIn caption celebrating the completion of this certificate."
    
    try:
        logger.info(f"Submitting image ({len(contents)} bytes, {mime_type}) to gemini-3.1-flash-lite")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[
                types.Part.from_bytes(
                    data=contents,
                    mime_type=mime_type,
                ),
                prompt_text
            ]
        )
        
        caption_text = response.text or "Caption generation completed, but returned empty text."
        return {"caption": caption_text}

    except Exception as e:
        logger.error(f"Gemini API execution error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate caption using Gemini model: {e}"
        )

# Endpoint 3: run-pipeline (handles both GET and POST for robustness)
@app.api_route("/api/run-pipeline", methods=["GET", "POST"])
async def run_pipeline():
    logger.info("Pipeline execution triggered")

    # a) Fetch data from YC index
    yc_url = "https://yc-oss.github.io/api/companies/all.json"
    try:
        logger.info(f"Fetching YC companies index from {yc_url}")
        res = requests.get(yc_url, timeout=10)
        res.raise_for_status()
        companies = res.json()
    except Exception as e:
        logger.error(f"Failed to fetch YC database: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to query YC database: {e}")

    if not isinstance(companies, list):
        raise HTTPException(status_code=502, detail="YC database returned invalid JSON schema.")

    # b) Filter for active robotics, AI, or automation companies
    filtered_companies = []
    for c in companies:
        if c.get("status") == "Active":
            # Extract tags, industry, subindustry, and description to match
            tags = [t.lower() for t in c.get("tags", [])]
            subindustry = (c.get("subindustry") or "").lower()
            description = (c.get("long_description") or "").lower()
            one_liner = (c.get("one_liner") or "").lower()

            match_words = ["robotics", "ai", "automation", "artificial intelligence"]
            
            is_match = (
                any(word in tags for word in match_words) or
                any(word in subindustry for word in match_words) or
                any(word in description for word in match_words) or
                any(word in one_liner for word in match_words)
            )

            if is_match:
                filtered_companies.append(c)

    if not filtered_companies:
        raise HTTPException(status_code=404, detail="No active robotics, AI, or automation companies found.")

    # c) Pick the first target company
    target = filtered_companies[0]
    company_name = target.get("name", "Unknown Company")
    one_liner = target.get("one_liner", "")
    description = target.get("long_description", "")
    website = target.get("website", "")
    logger.info(f"Selected pipeline target: {company_name}")

    # Generate 3-paragraph engineering pitch via gemini-3.1-flash-lite
    client = get_genai_client()
    pitch_prompt = (
        "Write a 3-paragraph engineering-focused LinkedIn pitch about this startup product:\n"
        f"Name: {company_name}\n"
        f"One-liner: {one_liner}\n"
        f"Description: {description}\n"
        f"Website: {website}\n\n"
        "Ensure the tone is highly professional, technical, engaging, and suitable for direct social media sharing."
    )

    try:
        logger.info(f"Querying gemini-3.1-flash-lite to draft pitch for {company_name}")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=pitch_prompt
        )
        pitch_text = response.text or "Drafted pitch content is empty."
    except Exception as e:
        logger.error(f"Failed to generate pitch with Gemini: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini pitch drafting failed: {e}")

    # d) LinkedIn Native Share API execution
    linkedin_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    linkedin_posted = False
    linkedin_response_info = {}

    if linkedin_token:
        try:
            logger.info("Executing LinkedIn API publish flow")
            headers = {
                "Authorization": f"Bearer {linkedin_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            }
            
            # Fetch profile owner URN dynamic lookup
            profile_url = "https://api.linkedin.com/v2/me"
            logger.info("Fetching profile owner ID from LinkedIn")
            profile_res = requests.get(profile_url, headers=headers, timeout=10)
            profile_res.raise_for_status()
            profile_data = profile_res.json()
            person_id = profile_data.get("id")
            
            if not person_id:
                raise Exception("Profile URN ID was missing in LinkedIn profile response.")
                
            person_urn = f"urn:li:person:{person_id}"

            # Construct share payload
            share_url = "https://api.linkedin.com/v2/shares"
            share_payload = {
                "owner": person_urn,
                "text": {
                    "text": pitch_text
                },
                "distribution": {
                    "linkedInDistributionTarget": {
                        "visibleToGuest": True
                    }
                }
            }
            
            logger.info(f"Posting share payload to {share_url}")
            share_res = requests.post(share_url, headers=headers, json=share_payload, timeout=10)
            share_res.raise_for_status()
            linkedin_response_info = share_res.json()
            linkedin_posted = True
            logger.info("Successfully shared target on LinkedIn!")

        except Exception as e:
            logger.error(f"LinkedIn posting failed: {e}")
            linkedin_response_info = {
                "status": "failed",
                "error": str(e),
                "message": "LinkedIn posting failed. The generated pitch was saved but not shared."
            }
    else:
        logger.info("LINKEDIN_ACCESS_TOKEN is missing. Skipping LinkedIn posting step.")
        linkedin_response_info = {
            "status": "skipped",
            "message": "LinkedIn post skipped because LINKEDIN_ACCESS_TOKEN is not configured."
        }

    # e) Return success summary
    return {
        "message": "Pipeline run completed.",
        "details": {
            "company": company_name,
            "pitch": pitch_text,
            "linkedin_posted": linkedin_posted,
            "linkedin_response": linkedin_response_info
        }
    }

if __name__ == "__main__":
    import uvicorn
    # Start app locally on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
