import os
import random
import logging
import asyncio
import re
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pydantic import BaseModel

class NewsRequest(BaseModel):
    title: str
    url: str

def extract_text_from_html(html_content: str) -> str:
    # Remove script and style elements
    html_content = re.sub(r'<(script|style)[^>]*>([\s\S]*?)<\/\1>', ' ', html_content, flags=re.IGNORECASE)
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_content)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:2000]


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

def extract_github_url(company: Dict[str, Any]) -> str | None:
    # 1. Check 'github' field
    github_val = company.get("github")
    if github_val and isinstance(github_val, str):
        github_val = github_val.strip()
        if "github.com" in github_val.lower():
            return github_val
        cleaned = github_val.strip("/")
        if cleaned:
            return f"https://github.com/{cleaned}"

    # 2. Check 'website' field
    website_val = company.get("website")
    if website_val and isinstance(website_val, str):
        website_val = website_val.strip()
        if "github.com" in website_val.lower():
            return website_val

    # 3. Check 'links' field/array
    links_val = company.get("links")
    if isinstance(links_val, list):
        for link in links_val:
            if isinstance(link, str):
                link = link.strip()
                if "github.com" in link.lower():
                    return link
            elif isinstance(link, dict):
                for val in link.values():
                    if isinstance(val, str):
                        val = val.strip()
                        if "github.com" in val.lower():
                            return val

    # 4. Regex search in long_description and one_liner
    pattern = r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+"
    for field in ["long_description", "one_liner"]:
        text = company.get(field)
        if text and isinstance(text, str):
            match = re.search(pattern, text)
            if match:
                return match.group(0)

    # 5. Popular lookup
    popular_repos = {
        "supabase": "https://github.com/supabase/supabase",
        "posthog": "https://github.com/PostHog/posthog",
        "airbyte": "https://github.com/airbytehq/airbyte",
        "twenty": "https://github.com/twentyhq/twenty",
        "anythingllm": "https://github.com/Mintplex-Labs/anything-llm",
        "highlight.io": "https://github.com/highlight/highlight",
        "citus data": "https://github.com/citusdata/citus",
        "lunasec": "https://github.com/lunasec-io/lunasec",
        "tracecat": "https://github.com/TracecatHQ/tracecat",
        "gitpod": "https://github.com/gitpod-io/gitpod",
        "gitlab": "https://github.com/gitlabhq/gitlabhq",
        "plangrid": "https://github.com/plangrid/plangrid",
        "apollo": "https://github.com/apollographql/apollo-client",
        "langchain": "https://github.com/langchain-ai/langchain",
        "ludwig": "https://github.com/ludwig-ai/ludwig",
        "redash": "https://github.com/getredash/redash",
        "dbt": "https://github.com/dbt-labs/dbt-core",
        "hasura": "https://github.com/hasura/graphql-engine",
        "gatsby": "https://github.com/gatsbyjs/gatsby",
        "daily.co": "https://github.com/daily-co/daily-js"
    }
    
    name_lower = company.get("name", "").lower().strip()
    slug_lower = company.get("slug", "").lower().strip()
    
    for name_key, repo_url in popular_repos.items():
        if re.search(rf"\b{re.escape(name_key)}\b", name_lower) or re.search(rf"\b{re.escape(name_key)}\b", slug_lower):
            if name_key == "apollo" and ("atomics" in name_lower or "space" in name_lower):
                continue
            return repo_url

    return None

def parse_batch_year(batch_str: str) -> int:
    if not batch_str:
        return 0
    for token in batch_str.split():
        if token.isdigit() and len(token) == 4:
            return int(token)
    return 0


# Endpoint 2: GET /api/discover-startups
@app.get("/api/discover-startups")
async def discover_startups(country: str = "All"):
    logger.info(f"Startup job-hunter pipeline triggered with country filter: {country}")

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

    # Apply geographical filter if country is not "All"
    if country.strip().lower() != "all":
        filtered_by_country = []
        country_lower = country.strip().lower()
        for c in active_companies:
            loc_fields = [
                c.get("all_locations"),
                c.get("location"),
                c.get("country"),
                c.get("hq"),
                c.get("city"),
                c.get("regions")
            ]
            loc_strings = []
            for lf in loc_fields:
                if isinstance(lf, str):
                    loc_strings.append(lf)
                elif isinstance(lf, list):
                    loc_strings.extend(str(item) for item in lf if item)
            loc_combined = ", ".join(loc_strings).lower()
            if country_lower in loc_combined:
                filtered_by_country.append(c)
        active_companies = filtered_by_country

        if not active_companies:
            logger.info(f"No active companies found matching country: {country}")
            return []

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
    
    combined = hiring_companies + other_companies
    
    # Separate companies with github from ones without to ensure we prioritize demo-ready repositories
    with_github = []
    without_github = []
    for c in combined:
        if extract_github_url(c) is not None:
            with_github.append(c)
        else:
            without_github.append(c)
            
    num_github_to_select = min(len(with_github), 2)
    selected_github = with_github[:num_github_to_select]
    selected_other = without_github[:(5 - num_github_to_select)]
    
    selected_companies = selected_github + selected_other
    random.shuffle(selected_companies)

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
        github_url = extract_github_url(c)
        
        results.append({
            "name": name,
            "batch": batch,
            "logo": logo,
            "website": website,
            "jobs_url": jobs_url,
            "contact_location": contact_location,
            "github_url": github_url,
            "AI_summary": summaries[i]
        })
        
    logger.info(f"Successfully processed and generated summaries for {len(results)} startups")
    return results

# Endpoint 3: POST /api/summarize-news
@app.post("/api/summarize-news")
async def summarize_news(request: NewsRequest):
    logger.info(f"Summarizing news article: {request.title} (URL: {request.url})")
    
    html_text = ""
    # Try fetching the URL content
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(request.url, headers=headers, timeout=8)
        res.raise_for_status()
        html_text = extract_text_from_html(res.text)
    except Exception as e:
        logger.warning(f"Failed to scrape URL {request.url}: {e}. Falling back to title-based summarization.")

    # Call Gemini model
    client = get_genai_client()
    
    # Prompt construction
    if html_text:
        prompt = (
            f"Article Title: {request.title}\n"
            f"Extracted Content: {html_text}\n"
        )
    else:
        prompt = (
            f"Article Title: {request.title}\n"
            "Scraping was blocked. Please summarize this article using its title and your internal knowledge."
        )

    system_instruction = (
        "You are an automated terminal system. Provide a strict, highly technical "
        "2-sentence summary of this news article. Do not use conversational filler. "
        "Output the response in plain text."
    )
    
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        summary = response.text.strip() if response.text else "No summary available."
        return {"summary": summary}
    except Exception as e:
        logger.error(f"Gemini API error during news summarization: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {e}"
        )

if __name__ == "__main__":
    import uvicorn
    # Start app locally on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
