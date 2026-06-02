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
    title="YC Startup Discovery Engine Backend",
    description="Core API engine for sourcing active YC startups and generating AI engineering summaries.",
    version="1.0.0"
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
    website = company.get("website", "")
    tags = company.get("tags", [])
    
    prompt = (
        "You are an expert technical analyst. Write a precise, exactly 2-sentence technical summary "
        "explaining the core engineering/technical innovation of this startup. Focus on *how* they build it, "
        "their architecture, stack, or core technical value proposition. Do not include marketing fluff.\n\n"
        f"Startup Name: {name}\n"
        f"One-liner: {one_liner}\n"
        f"Description: {description}\n"
        f"Website: {website}\n"
        f"Tags: {', '.join(tags)}\n\n"
        "Remember, your output must be exactly two sentences."
    )
    
    try:
        # Since client.models.generate_content is synchronous, we run it in a thread pool
        # to prevent blocking the event loop, allowing 5 API requests to execute in parallel.
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

# Endpoint 2: GET /api/discover-startups
@app.get("/api/discover-startups")
async def discover_startups():
    logger.info("Startup discovery pipeline triggered")

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

    # b) Filter for "Active" companies
    active_companies = [c for c in companies if c.get("status") == "Active"]
    if not active_companies:
        raise HTTPException(status_code=404, detail="No active companies found in the YC database.")

    # c) Partition companies based on priority tags
    priority_keywords = {"ai", "robotics", "developer tools", "artificial intelligence", "developer-tools", "dev tools", "machine learning", "ml"}
    
    priority_companies = []
    other_companies = []
    
    for c in active_companies:
        tags = [t.lower() for t in c.get("tags", [])]
        is_priority = any(keyword in tags for keyword in priority_keywords)
        if is_priority:
            priority_companies.append(c)
        else:
            other_companies.append(c)
            
    # Shuffle lists to ensure dynamic results on every call
    random.shuffle(priority_companies)
    random.shuffle(other_companies)
    
    # Grab 5 startups, prioritizing the priority tags
    selected_companies = (priority_companies + other_companies)[:5]
    
    # d) Fetch GenAI Client
    client = get_genai_client()
    
    # e) Generate 2-sentence technical summaries in parallel
    tasks = [generate_company_summary(client, c) for c in selected_companies]
    summaries = await asyncio.gather(*tasks)
    
    # f) Formulate final JSON response array
    results = []
    for i, c in enumerate(selected_companies):
        results.append({
            "name": c.get("name", "Unknown Company"),
            "batch": c.get("batch", "Unknown Batch"),
            "website": c.get("website", ""),
            "summary": summaries[i]
        })
        
    logger.info(f"Successfully processed and generated summaries for {len(results)} startups")
    return results

if __name__ == "__main__":
    import uvicorn
    # Start app locally on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
