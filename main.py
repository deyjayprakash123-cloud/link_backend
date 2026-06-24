import os
import random
import logging
import asyncio
import re
import json
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

def interleave_lists(lists: List[List[Any]]) -> List[Any]:
    interleaved = []
    max_len = max(len(l) for l in lists) if lists else 0
    for i in range(max_len):
        for l in lists:
            if i < len(l):
                interleaved.append(l[i])
    return interleaved

async def fetch_yc_companies() -> List[Dict[str, Any]]:
    url = "https://yc-oss.github.io/api/companies/all.json"
    try:
        logger.info("Fetching YC companies for radar...")
        res = await asyncio.to_thread(requests.get, url, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not isinstance(data, list):
            logger.warning("YC Open Source did not return a list")
            return []
        
        results = []
        for c in data:
            if c.get("status") == "Active":
                loc = c.get("all_locations") or c.get("location") or "Remote/Global"
                desc = c.get("long_description") or c.get("one_liner") or ""
                url_val = c.get("website") or c.get("url") or ""
                github_url = extract_github_url(c)
                results.append({
                    "name": c.get("name") or "Unknown Company",
                    "platform": "YC Open Source",
                    "location": loc,
                    "url": url_val,
                    "description": desc,
                    "batch": c.get("batch") or "Unknown Batch",
                    "github_url": github_url
                })
        return results
    except Exception as e:
        logger.error(f"Error fetching YC companies: {e}")
        return []

async def fetch_arbeitnow_jobs() -> List[Dict[str, Any]]:
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        logger.info("Fetching Arbeitnow jobs for radar...")
        res = await asyncio.to_thread(requests.get, url, timeout=10)
        res.raise_for_status()
        data = res.json()
        jobs = data.get("data", []) if isinstance(data, dict) else []
        
        results = []
        for item in jobs:
            title = item.get("title") or ""
            desc = extract_text_from_html(item.get("description") or "")
            raw_desc = f"{title}. {desc}" if desc else title
            loc = item.get("location") or "Remote/Global"
            url_val = item.get("url") or ""
            results.append({
                "name": item.get("company_name") or "Unknown Company",
                "platform": "Global Job Engine",
                "location": loc,
                "url": url_val,
                "description": raw_desc
            })
        return results
    except Exception as e:
        logger.error(f"Error fetching Arbeitnow jobs: {e}")
        return []

async def fetch_github_trending() -> List[Dict[str, Any]]:
    url = "https://github.com/trending"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        logger.info("Fetching GitHub Trending repositories...")
        res = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
        res.raise_for_status()
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.find_all("article", class_="Box-row")
        
        results = []
        for a in articles:
            h2 = a.find("h2")
            if not h2:
                continue
            anchor = h2.find("a")
            if not anchor:
                continue
            
            href = anchor.get("href", "")
            repo_path = href.strip("/")
            repo_url = f"https://github.com/{repo_path}"
            
            name_text = anchor.get_text(strip=True).replace("\n", "").replace(" ", "")
            
            desc_p = a.find("p", class_=lambda c: c and "col-9" in c)
            description = desc_p.get_text(strip=True) if desc_p else ""
            
            results.append({
                "name": name_text,
                "platform": "GitHub Trending",
                "location": "Remote/Global",
                "url": repo_url,
                "description": description
            })
        return results
    except Exception as e:
        logger.error(f"Error fetching GitHub Trending: {e}")
        return []

async def generate_radar_diagnostic(client: genai.Client | None, company: Dict[str, Any]) -> str:
    if not client:
        return "> ERROR: TELEMETRY_UNAVAILABLE"
        
    name = company.get("name", "Unknown Company")
    platform = company.get("platform", "Unknown")
    description = company.get("description", "")
    
    prompt = (
        f"Company Name: {name}\n"
        f"Platform: {platform}\n"
        f"Description:\n{description}\n"
    )
    
    system_instruction = (
        "You are an integrated terminal analyzer. Read the provided company description. "
        "Output a strict 2-sentence technical diagnostic outlining: "
        "1) Their infrastructure/product niche, and "
        "2) The exact developer stack or skill set that aligns with their engineering needs. "
        "No conversational filler."
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
        return response.text.strip() if response.text else "> ERROR: TELEMETRY_UNAVAILABLE"
    except Exception as e:
        logger.error(f"Gemini API error for global-radar entity {name}: {e}")
        return "> ERROR: TELEMETRY_UNAVAILABLE"

@app.get("/api/global-radar")
async def global_radar(country: str = "All", limit: int = 5, source: str = "ALL"):
    logger.info(f"Global Tech Radar query triggered with country: {country}, limit: {limit}, source: {source}")
    
    # Fetch concurrently from YC, Arbeitnow, and GitHub Trending
    stream_results = await asyncio.gather(
        fetch_yc_companies(),
        fetch_arbeitnow_jobs(),
        fetch_github_trending()
    )
    
    valid_lists = [lst for lst in stream_results if lst]
    
    if not valid_lists:
        raise HTTPException(
            status_code=502,
            detail="Failed to retrieve data from any of the requested data sources."
        )
        
    combined = interleave_lists(valid_lists)
    
    # Strict Regional Filtering: case-insensitive filter
    if country and country.lower() != "all":
        country_lower = country.lower().strip()
        combined = [item for item in combined if country_lower in item.get("location", "").lower()]
        
    # Safe Slicing: Slice only AFTER the regional filter has been applied
    combined = combined[:limit]
    
    # Initialize GenAI Client safely
    try:
        client = get_genai_client()
    except Exception as e:
        logger.error(f"Failed to initialize GenAI Client for global-radar telemetry: {e}")
        client = None
    
    # Loop through the safely sliced list to generate the 2-sentence summaries
    logger.info(f"Processing Gemini telemetry diagnostic for a batch of {len(combined)} companies...")
    telemetry_tasks = [generate_radar_diagnostic(client, comp) for comp in combined]
    diagnostics = await asyncio.gather(*telemetry_tasks)
    
    # Add telemetry_diagnostic and frontend aliases
    for i, item in enumerate(combined):
        diag = diagnostics[i]
        item["telemetry_diagnostic"] = diag
        item["AI_summary"] = diag
        item["origin_platform"] = item["platform"]
        item["hq_location"] = item["location"]
        item["contact_location"] = item["location"]
        item["target_link"] = item["url"]
        item["jobs_url"] = item["url"]
        item["raw_description"] = item["description"]
        if "batch" not in item:
            item["batch"] = "Global"
            
    logger.info(f"Global Tech Radar returned {len(combined)} items.")
    return combined

def extract_org_name(github_url: str | None) -> str | None:
    if not github_url:
        return None
    url = github_url.strip().rstrip("/")
    match = re.search(r"github\.com/([a-zA-Z0-9_\-]+)", url, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

async def get_github_org(github_token: str | None, startup_name: str) -> str | None:
    headers = {"User-Agent": "Global-Radar-App"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    clean_name = re.sub(r"[^a-zA-Z0-9\-]", "", startup_name).strip()
    if not clean_name:
        return None
    url = f"https://api.github.com/search/users?q={clean_name}+type:org"
    try:
        res = await asyncio.to_thread(requests.get, url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            if items:
                return items[0].get("login")
    except Exception as e:
        logger.warning(f"Error searching org for {startup_name}: {e}")
    return clean_name

async def fetch_startup_issues(
    org_name: str,
    github_token: str | None,
    user_core_language: str = "Python"
) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "Global-Radar-App",
        "Accept": "application/vnd.github.v3+json"
    }
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    def parse_issues(items: list) -> List[Dict[str, Any]]:
        results = []
        for issue in items[:2]:
            # Extract repo name from repository_url field
            repo_url = issue.get("repository_url", "")
            repo_name = repo_url.split("/")[-1] if repo_url else ""
            results.append({
                "title": issue.get("title", "Open Issue"),
                "url": issue.get("html_url", ""),
                "repo_name": repo_name
            })
        return results

    try:
        # STEP 1: Search the specific startup org
        q_org = f'org:{org_name} state:open label:"good first issue"'
        url_org = f"https://api.github.com/search/issues?q={requests.utils.quote(q_org)}&sort=updated&order=desc"
        res_org = await asyncio.to_thread(requests.get, url_org, headers=headers, timeout=8)
        if res_org.status_code == 200:
            items = res_org.json().get("items", [])
            if items:
                return parse_issues(items)

        # STEP 2: CRITICAL FALLBACK — search globally for the user's core language
        logger.info(f"No issues found for org '{org_name}'. Falling back to global '{user_core_language}' good first issues.")
        q_global = f'state:open label:"good first issue" language:{user_core_language}'
        url_global = f"https://api.github.com/search/issues?q={requests.utils.quote(q_global)}&sort=updated&order=desc"
        res_global = await asyncio.to_thread(requests.get, url_global, headers=headers, timeout=8)
        if res_global.status_code == 200:
            items = res_global.json().get("items", [])
            if items:
                return parse_issues(items)

        return []
    except Exception as e:
        logger.warning(f"Failed to fetch issues for org {org_name}: {e}")
        return []

async def generate_blueprint_card(
    client: genai.Client | None,
    user_stack: List[str],
    deep_dependencies: List[str],
    startup: Dict[str, Any],
    live_issues: List[Dict[str, Any]]
) -> Dict[str, Any]:
    startup_name = startup.get("name", "Unknown")
    startup_desc = startup.get("description") or startup.get("raw_description") or ""

    # Offline fallback — no Gemini needed
    def get_fallback():
        action_plan = "Submit a PR to their open-source repository to demonstrate your production coding abilities."
        if live_issues:
            action_plan = f"Fix '{live_issues[0]['title']}' to get direct visibility with their engineering team."
        return {
            "startup_name": startup_name,
            "startup_description": startup_desc[:300] if startup_desc else "",
            "live_issues": live_issues[:2],
            "action_plan": action_plan
        }

    if not client:
        return get_fallback()

    prompt = f"""
[USER TECH PROFILE]
Languages: {json.dumps(user_stack)}
Frameworks / Deep Dependencies: {json.dumps(deep_dependencies)}

[TARGET STARTUP]
Name: {startup_name}
Description: {startup_desc[:400]}

[LIVE OPEN-SOURCE ISSUES FOR THIS STARTUP]
{json.dumps(live_issues)}

OPERATIONAL INSTRUCTIONS:
- Write a crisp 1-2 sentence `startup_description` summarising what this company builds.
- Pass through the `live_issues` array exactly as provided.
- Write a punchy 1-sentence `action_plan` that connects these specific issues to the user's stack
  (e.g., "Close this open TypeScript issue to get your name in front of their core team before applying.").
"""

    system_instruction = (
        "You are a technical career strategist. Analyse the provided data and output a RAW JSON object with EXACTLY these keys:\n"
        "- `startup_name` (string)\n"
        "- `startup_description` (string, 1-2 crisp sentences)\n"
        "- `live_issues` (array — pass the provided issues through unchanged, each object must have: `title`, `url`, `repo_name`)\n"
        "- `action_plan` (string, 1 punchy sentence tying the issues to the user's specific skills)\n"
        "Output ONLY valid JSON. No markdown fences."
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json"
            )
        )
        response_text = response.text.strip() if response.text else "{}"
        try:
            card = json.loads(response_text)
            required_keys = {"startup_name", "startup_description", "live_issues", "action_plan"}
            if isinstance(card, dict) and required_keys.issubset(card.keys()):
                # Safety: ensure live_issues always has title/url/repo_name keys
                sanitised = []
                for iss in (card.get("live_issues") or [])[:2]:
                    if isinstance(iss, dict):
                        sanitised.append({
                            "title": iss.get("title", "Open Issue"),
                            "url": iss.get("url", ""),
                            "repo_name": iss.get("repo_name", "")
                        })
                card["live_issues"] = sanitised
                return card
            else:
                logger.warning(f"Gemini response missing keys for {startup_name}. Falling back.")
                return get_fallback()
        except Exception as e:
            logger.error(f"JSON parse error for {startup_name}: {e}")
            return get_fallback()
    except Exception as e:
        logger.error(f"Gemini API error for {startup_name}: {e}")
        return get_fallback()


@app.get("/api/blueprint")
async def get_blueprint(github_username: str, limit: int = 5):
    logger.info(f"OSS Backdoor Blueprint triggered for GitHub user: {github_username} (limit: {limit})")
    try:
        # 1. Fetch GitHub profile repos
        github_token = os.getenv("GITHUB_TOKEN")
        headers = {"User-Agent": "Global-Radar-App"}
        if github_token:
            headers["Authorization"] = f"token {github_token}"

        github_url = f"https://api.github.com/users/{github_username}/repos?sort=updated&per_page=10"
        res = await asyncio.to_thread(requests.get, github_url, headers=headers, timeout=10)
        if res.status_code == 404:
            return {"error": "GitHub profile not found."}
        res.raise_for_status()
        repos = res.json()

        # 2. Extract unique programming languages and determine the user's #1 core language
        lang_counter: Dict[str, int] = {}
        if isinstance(repos, list):
            for repo in repos:
                if not isinstance(repo, dict):
                    continue
                lang = repo.get("language")
                if lang and isinstance(lang, str):
                    lang_counter[lang] = lang_counter.get(lang, 0) + 1

        user_stack = list(lang_counter.keys())
        # Pick the most frequent language as the core language for the global fallback
        user_core_language = max(lang_counter, key=lang_counter.get) if lang_counter else "Python"
        logger.info(f"User stack: {user_stack} | Core language: {user_core_language}")

        # 3. Deep Scan: extract framework dependencies from package.json / requirements.txt
        top_repos = repos[:3] if isinstance(repos, list) else []
        deep_dependencies: set = set()

        async def fetch_raw_contents(r_name: str, filename: str):
            url = f"https://api.github.com/repos/{github_username}/{r_name}/contents/{filename}"
            raw_headers = {
                "Accept": "application/vnd.github.v3.raw",
                "User-Agent": "Global-Radar-App"
            }
            if github_token:
                raw_headers["Authorization"] = f"token {github_token}"
            try:
                r = await asyncio.to_thread(requests.get, url, headers=raw_headers, timeout=5)
                if r.status_code == 200:
                    return r.text
            except Exception as e:
                logger.error(f"Error fetching {filename} for {r_name}: {e}")
            return None

        scan_tasks = []
        for r in top_repos:
            r_name = r.get("name")
            if r_name and isinstance(r_name, str):
                scan_tasks.append((r_name, "package.json"))
                scan_tasks.append((r_name, "requirements.txt"))

        if scan_tasks:
            contents = await asyncio.gather(*(fetch_raw_contents(r_name, fname) for r_name, fname in scan_tasks))
            for (r_name, fname), content in zip(scan_tasks, contents):
                if not content:
                    continue
                if fname == "package.json":
                    try:
                        data = json.loads(content)
                        if isinstance(data, dict):
                            for k in {**data.get("dependencies", {}), **data.get("devDependencies", {})}.keys():
                                deep_dependencies.add(k)
                    except Exception as ex:
                        logger.warning(f"Error parsing package.json for {r_name}: {ex}")
                elif fname == "requirements.txt":
                    try:
                        for line in content.splitlines():
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            pkg_name = re.split(r'==|>=|<=|~=|>|<', line)[0].strip()
                            if pkg_name:
                                deep_dependencies.add(pkg_name)
                    except Exception as ex:
                        logger.warning(f"Error parsing requirements.txt for {r_name}: {ex}")

        deep_dependencies_list = list(deep_dependencies)
        logger.info(f"Aggregated deep dependencies: {deep_dependencies_list}")

        # 4. Source startups
        stream_results = await asyncio.gather(
            fetch_yc_companies(),
            fetch_arbeitnow_jobs()
        )
        valid_lists = [lst for lst in stream_results if lst]
        if not valid_lists:
            return {"error": "Failed to retrieve startup data from any of the data sources."}
        combined = interleave_lists(valid_lists)

        valid_pool = [
            item for item in combined
            if item.get("name") and (item.get("description") or item.get("raw_description"))
        ]
        if not valid_pool:
            return {"error": "No valid startups with descriptions found."}

        startups = random.sample(valid_pool, min(len(valid_pool), limit))

        # 5. Resolve org names and fetch live issues with guaranteed fallback
        formatted_startups = []
        for s in startups:
            github_url_val = s.get("github_url")
            org_name = extract_org_name(github_url_val)
            formatted_startups.append({
                "name": s.get("name", "Unknown"),
                "description": s.get("description") or s.get("raw_description") or "",
                "github_url": github_url_val,
                "org_name": org_name
            })

        async def prepare_startup(s):
            o_name = s.get("org_name")
            if not o_name:
                o_name = await get_github_org(github_token, s["name"])
            issues = await fetch_startup_issues(
                o_name or s["name"],
                github_token,
                user_core_language
            )
            return o_name, issues

        logger.info("Resolving org names and fetching live OSS issues...")
        org_and_issues = await asyncio.gather(*(prepare_startup(s) for s in formatted_startups))
        for idx, s in enumerate(formatted_startups):
            s["org_name"] = org_and_issues[idx][0]
            s["live_issues"] = org_and_issues[idx][1]

        # 6. Generate blueprint cards via Gemini
        client = None
        try:
            client = get_genai_client()
        except Exception as e:
            logger.warning(f"GenAI Client init failed, using offline heuristics: {e}")

        logger.info("Generating OSS blueprint cards...")
        blueprint_tasks = [
            generate_blueprint_card(client, user_stack, deep_dependencies_list, s, s.get("live_issues", []))
            for s in formatted_startups
        ]
        blueprint = list(await asyncio.gather(*blueprint_tasks))

        return {"blueprint": blueprint}

    except Exception as e:
        logger.error(f"High-level error in get_blueprint: {e}")
        return {"error": f"Failed to retrieve blueprint data: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    # Start app locally on port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

