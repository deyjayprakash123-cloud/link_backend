import requests
import re
from typing import Dict, Any

yc_url = "https://yc-oss.github.io/api/companies/all.json"
res = requests.get(yc_url, timeout=10)
companies = res.json()

def extract_github_url(company: Dict[str, Any]) -> str | None:
    github_val = company.get("github")
    if github_val and isinstance(github_val, str):
        github_val = github_val.strip()
        if "github.com" in github_val.lower():
            return github_val
        cleaned = github_val.strip("/")
        if cleaned:
            return f"https://github.com/{cleaned}"

    website_val = company.get("website")
    if website_val and isinstance(website_val, str):
        website_val = website_val.strip()
        if "github.com" in website_val.lower():
            return website_val

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

    # Regex search in long_description and one_liner
    pattern = r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+"
    for field in ["long_description", "one_liner"]:
        text = company.get(field)
        if text and isinstance(text, str):
            match = re.search(pattern, text)
            if match:
                return match.group(0)

    # Popular lookup
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
    
    name_lower = company.get("name", "").lower()
    for name_key, repo_url in popular_repos.items():
        if name_key in name_lower:
            return repo_url
            
    slug_lower = company.get("slug", "").lower()
    for name_key, repo_url in popular_repos.items():
        if name_key in slug_lower:
            return repo_url

    return None

def parse_batch_year(batch_str: str) -> int:
    if not batch_str:
        return 0
    for token in batch_str.split():
        if token.isdigit() and len(token) == 4:
            return int(token)
    return 0

active_companies = [c for c in companies if c.get("status") == "Active"]
active_companies.sort(key=lambda x: parse_batch_year(x.get("batch")), reverse=True)
max_year = parse_batch_year(active_companies[0].get("batch"))
newest_companies = [c for c in active_companies if parse_batch_year(c.get("batch")) >= max_year - 2]

print("Total newest companies:", len(newest_companies))
found = []
for c in newest_companies:
    g = extract_github_url(c)
    if g:
        found.append((c.get("name"), c.get("batch"), g))

print(f"Found {len(found)} companies with GitHub in the newest batches:")
for f in found:
    print(f)
