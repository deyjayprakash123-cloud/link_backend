import os
import random
import logging
import asyncio
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from google import genai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("launchoutreach-backend")

# Load environment variables from .env file if present
load_dotenv()

app = FastAPI(
    title="YC Startup Job-Hunter Discovery Engine Backend",
    description="API engine for sourcing active, growing YC startups and identifying target candidates for application.",
    version="1.1.0"
)

# CORS Setup: Allow all origins so frontend can communicate
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

# Helper to generate AI summary for a single company using gemini-3.1-flash-lite
async def generate_company_summary(client: genai.Client, company: Dict[str, Any]) -> str:
    name = company.get("name", "Unknown Company")
    one_liner = company.get("one_liner", "")
    description = company.get("long_description", "")
    tags = company.get("tags", [])
    
    prompt = (
        "You are an expert technical recruiter. Analyze the following startup details "
        "and generate a clean, exactly 2-sentence summary answering:\n"
        "1. What core engineering/technical solution do they solve?\n"
        "2. What specific kind of technical applicants or engineers would thrive here (e.g. background, stack, mindset)?\n\n"
        f"Startup Name: {name}\n"
        f"One-liner: {one_liner}\n"
        f"Description: {description}\n"
        f"Tags: {', '.join(tags)}\n\n"
        "Remember, your output must be exactly two sentences and contain no markdown formatting or labels."
    )
    
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=prompt
        )
        summary = response.text.strip() if response.text else "No summary available."
        return summary
    except Exception as e:
        logger.error(f"Gemini API error for {name}: {e}")
        return "Failed to generate technical summary due to API error."

def parse_batch_year(batch_str: str) -> int:
    if not batch_str:
        return 0
    for token in batch_str.split():
        if token.isdigit() and len(token) == 4:
            return int(token)
    return 0

# Endpoint 2: GET /api/discover-startups
@app.get("/api/discover-startups")
async def discover_startups():
    logger.info("Startup job-hunter pipeline triggered")

    # a) Fetch master JSON from YC index
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

    # b) Filter active companies
    active_companies = [c for c in companies if c.get("status") == "Active"]
    if not active_companies:
        raise HTTPException(status_code=404, detail="No active companies found in the YC database.")

    # c) Parse batch years and determine maximum year to find newest batches
    active_companies.sort(key=lambda x: parse_batch_year(x.get("batch")), reverse=True)
    
    # Target the newest high-growth batches (max_year and max_year - 1, e.g., 2025/2026)
    max_year = parse_batch_year(active_companies[0].get("batch"))
    newest_companies = [c for c in active_companies if parse_batch_year(c.get("batch")) >= max_year - 2]
    
    if not newest_companies:
        newest_companies = active_companies[:100]

    # Prioritize companies that are actively looking for candidates (isHiring is True)
    hiring_companies = [c for c in newest_companies if c.get("isHiring") is True]
    other_companies = [c for c in newest_companies if c.get("isHiring") is not True]
    
    # Shuffle to ensure dynamic discoveries
    random.shuffle(hiring_companies)
    random.shuffle(other_companies)
    
    selected_companies = (hiring_companies + other_companies)[:5]

    # d) Fetch GenAI Client
    client = get_genai_client()

    # e) Generate 2-sentence technical summaries in parallel
    tasks = [generate_company_summary(client, c) for c in selected_companies]
    summaries = await asyncio.gather(*tasks)

    # f) Formulate final JSON response array
    results = []
    for i, c in enumerate(selected_companies):
        name = c.get("name", "Unknown Company")
        batch = c.get("batch", "Unknown Batch")
        logo = c.get("small_logo_thumb_url") or ""
        website = c.get("website") or ""
        
        # Build direct-to-careers url or fall back to YC WorkAtAStartup
        jobs_url = f"{website.rstrip('/')}/careers" if website else "https://www.ycombinator.com/jobs/role/"
        contact_location = c.get("all_locations") or "Remote / San Francisco"
        
        results.append({
            "name": name,
            "batch": batch,
            "logo": logo,
            "website": website,
            "jobs_url": jobs_url,
            "contact_location": contact_location,
            "AI_summary": summaries[i]
        })
        
    logger.info(f"Successfully processed and generated summaries for {len(results)} startups")
    return results

if __name__ == "__main__":
    import uvicorn
    # Start app locally on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
