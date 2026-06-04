import requests

yc_url = "https://yc-oss.github.io/api/companies/all.json"
print("Fetching companies...")
res = requests.get(yc_url, timeout=10)
companies = res.json()

open_source_companies = []
for c in companies:
    tags = [t.lower() for t in c.get("tags", [])]
    if "open source" in tags or "developer tools" in tags or "dev tools" in tags:
        open_source_companies.append(c)

print(f"Total open source / devtools companies: {len(open_source_companies)}")
print("Sample tags and fields for first 5:")
for c in open_source_companies[:5]:
    print(f"Name: {c.get('name')}, Website: {c.get('website')}, Tags: {c.get('tags')}")
