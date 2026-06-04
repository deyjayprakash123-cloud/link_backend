import requests
import concurrent.futures

yc_url = "https://yc-oss.github.io/api/companies/all.json"
print("Fetching companies...")
res = requests.get(yc_url, timeout=10)
companies = res.json()

target_companies = []
for c in companies:
    tags = [t.lower() for t in c.get("tags", [])]
    if "open source" in tags or "developer tools" in tags or "dev tools" in tags:
        target_companies.append(c)

print(f"Total target companies: {len(target_companies)}")

def check_detail(c):
    url = c.get("api")
    if not url:
        return None
    try:
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            data = r.json()
            # Check for keys of interest
            keys = set(data.keys())
            has_github = any("git" in k.lower() for k in keys) or any("link" in k.lower() for k in keys)
            
            # Check if value contains github.com
            has_github_val = False
            for k, v in data.items():
                if "github.com" in str(v).lower() and k != "api":
                    has_github_val = True
            
            if has_github or has_github_val:
                return {
                    "name": c.get("name"),
                    "keys": list(keys),
                    "data": {k: v for k, v in data.items() if "github.com" in str(v).lower() or "git" in k.lower() or "link" in k.lower()}
                }
    except Exception:
        pass
    return None

results = []
print("Scanning in parallel...")
with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
    futures = [executor.submit(check_detail, c) for c in target_companies]
    for fut in concurrent.futures.as_completed(futures):
        res = fut.result()
        if res:
            results.append(res)
            print(f"Found match: {res['name']} - keys: {res['keys']}")

print(f"Scan complete. Found {len(results)} matches.")
