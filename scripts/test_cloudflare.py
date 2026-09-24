import json
import urllib.request
import re

url = "https://www.finextra.com/newsarticle/48462/former-visa-crypto-lead-launches-open-payments-network?utm_medium=rssfinextra&utm_source=finextrafeed"

def test_crawl_cdp():
    print(f"\n--- Testing: Crawl4AI over CDP to host Chrome ---")
    payload = {
        "urls": [url],
        "browser_config": {
            "type": "BrowserConfig",
            "params": {
                "cdp_url": "http://0.250.250.254:9222",
                "headless": False,
            },
        },
        "crawler_config": {
            "type": "CrawlerRunConfig",
            "params": {
                "delay_before_return_html": 3.0,
                "wait_until": "domcontentloaded",
            },
        },
    }
    
    req = urllib.request.Request(
        "http://127.0.0.1:11235/crawl",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results") or [data]
            res = results[0]
            html = res.get("html") or res.get("cleaned_html") or ""
            title = ""
            m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
            if m:
                title = m.group(1).strip()
            print(f"Success: {res.get('success')}")
            print(f"Title: {title}")
            print(f"HTML len: {len(html)}")
            if "Just a moment..." in title or "cf-challenge" in html:
                print(">> [BLOCKED / CLOUDFLARE CHALLENGE]")
            else:
                print(">> [PASSED CLOUDFLARE!]")
    except urllib.error.HTTPError as e:
        print("HTTP Error:", e.code, e.reason)
        try:
            print("Error body:", e.read().decode("utf-8")[:300])
        except Exception:
            pass
    except Exception as e:
        print("Request failed:", e)

if __name__ == "__main__":
    test_crawl_cdp()
