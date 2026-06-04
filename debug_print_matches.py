import requests

urls = [
    "https://yc-oss.github.io/api/batches/winter-2013/citus-data.json",
    "https://yc-oss.github.io/api/batches/summer-2020/airbyte.json",
    "https://yc-oss.github.io/api/batches/summer-2023/anythingllm.json",
    "https://yc-oss.github.io/api/batches/summer-2021/highlight-io.json",
    "https://yc-oss.github.io/api/batches/winter-2023/twenty.json",
    "https://yc-oss.github.io/api/batches/winter-2024/tracecat.json"
]

for url in urls:
    print(f"URL: {url}")
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            print("Name:", data.get("name"))
            print("Website:", data.get("website"))
            # Print any fields matching github or containing github
            for k, v in data.items():
                if "github.com" in str(v).lower() and k != "api":
                    print(f"  {k}: {v}")
            print("-" * 50)
    except Exception as e:
        print("Error:", e)
