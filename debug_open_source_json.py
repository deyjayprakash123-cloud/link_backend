import requests

tag_url = "https://yc-oss.github.io/api/tags/open-source.json"
print(f"Fetching from {tag_url}...")
try:
    res = requests.get(tag_url, timeout=10)
    if res.status_code == 200:
        data = res.json()
        print(f"Loaded {len(data)} companies.")
        if data:
            print("First item keys:", list(data[0].keys()))
            print("First item content:", data[0])
    else:
        print(f"Failed with status: {res.status_code}")
except Exception as e:
    print(f"Error: {e}")
