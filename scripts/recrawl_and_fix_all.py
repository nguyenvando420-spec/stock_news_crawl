#!/usr/bin/env python3
"""
Comprehensive batch repair and re-crawler script.
Scans all articles in output/articles.jsonl and PostgreSQL.
Re-crawls and re-extracts any article with missing, truncated, or low-quality content (< 500 chars).
"""

import os
import sys
import json
import time
import yaml
from pathlib import Path
import httpx

root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/app")
sys.path.insert(0, str(root_dir / "crawler"))

from crawler.extractor import extract_article_data, is_cloudflare_challenge
from crawler.cdp import is_cdp_available, fetch_via_cdp

try:
    import psycopg
except ImportError:
    psycopg = None


def run_repair():
    sources_path = os.getenv("SOURCES_FILE", "/config/sources.yaml")
    if not os.path.exists(sources_path):
        sources_path = str(root_dir / "config" / "sources.yaml")

    with open(sources_path, "r", encoding="utf-8") as f:
        sources_cfg = (yaml.safe_load(f) or {}).get("sources", {})

    jsonl_path = Path(os.getenv("OUTPUT_FILE", "/data/articles.jsonl"))
    if not jsonl_path.exists():
        jsonl_path = root_dir / "output" / "articles.jsonl"

    print(f"Loading articles from {jsonl_path}...")
    articles_map = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                url = item.get("url")
                if url:
                    articles_map[url] = item
            except Exception:
                pass

    total = len(articles_map)
    print(f"Total unique articles: {total}")

    # Identify items that need repair: len(content_markdown) < 500 or challenge or title is Just a moment...
    to_repair = []
    for url, item in articles_map.items():
        content = (item.get("content_markdown") or "").strip()
        title = (item.get("title") or "").strip()
        is_bad = (
            len(content) < 500
            or is_cloudflare_challenge(content, title)
            or title == "Just a moment..."
            or "automated access to our sites must comply" in content.lower()
        )
        if is_bad:
            to_repair.append(item)

    print(f"Identified {len(to_repair)} articles needing content re-crawl / repair.")

    crawl4ai_url = os.getenv("CRAWL4AI_URL", "http://crawl4ai:11235")
    cdp_ready = is_cdp_available()
    print(f"Crawl4AI URL: {crawl4ai_url} | CDP Available: {cdp_ready}")

    fixed_count = 0
    client = httpx.Client(timeout=30)

    for i, item in enumerate(to_repair, 1):
        url = item.get("url")
        source_id = item.get("source")
        cfg = sources_cfg.get(source_id, {})
        old_len = len((item.get("content_markdown") or "").strip())
        print(f"\n[{i}/{len(to_repair)}] Repairing ({source_id}): {url}")
        print(f"   Current content length: {old_len}")

        html = None

        # 1. Try Crawl4AI
        try:
            payload = {
                "urls": [url],
                "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
                "crawler_config": {"type": "CrawlerRunConfig", "params": {"word_count_threshold": 10, "magic": True}}
            }
            resp = client.post(f"{crawl4ai_url}/crawl", json=payload)
            if resp.status_code == 200:
                res = resp.json().get("results", [{}])[0]
                html = res.get("html") or res.get("cleaned_html")
        except Exception as e:
            print(f"   Crawl4AI error: {e}")

        # 2. If blocked or empty, try CDP fallback
        if not html or len(html.strip()) < 200 or is_cloudflare_challenge(html):
            if cdp_ready:
                print("   Attempting CDP fallback...")
                try:
                    cdp_html = fetch_via_cdp(url, timeout=18)
                    if cdp_html and not is_cloudflare_challenge(cdp_html):
                        html = cdp_html
                        print("   CDP fallback succeeded!")
                except Exception as ce:
                    print(f"   CDP error: {ce}")

        # 3. If still no HTML, try standard HTTP
        if not html or len(html.strip()) < 200:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}
                h_resp = client.get(url, headers=headers, follow_redirects=True)
                if h_resp.status_code == 200:
                    html = h_resp.text
            except Exception:
                pass

        if not html:
            print("   Failed to fetch HTML. Skipping.")
            continue

        extracted = extract_article_data(html, cfg, item)
        new_content = (extracted.get("content_markdown") or "").strip()
        new_len = len(new_content)

        if new_len > old_len or new_len > 450:
            item["title"] = extracted.get("title") or item.get("title")
            item["description"] = extracted.get("description") or item.get("description")
            item["author"] = extracted.get("author") or item.get("author")
            item["content_markdown"] = extracted.get("content_markdown")
            item["content_html"] = extracted.get("content_html")
            articles_map[url] = item
            fixed_count += 1
            print(f"   Fixed! Content length: {old_len} -> {new_len}")
        else:
            print(f"   Extracted length ({new_len}) was not better than old ({old_len}).")

        time.sleep(0.5)

    client.close()

    print(f"\n==========================================")
    print(f"Repair finished! Successfully repaired {fixed_count} / {len(to_repair)} articles.")
    print(f"Saving updated articles to {jsonl_path}...")

    # Write back to JSONL
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for it in articles_map.values():
            f.write(json.dumps(it, ensure_ascii=False, default=str) + "\n")
    print("Saved JSONL successfully!")

    # Update PostgreSQL
    db_url = os.getenv("DATABASE_URL")
    if db_url and psycopg:
        print("Updating PostgreSQL database...")
        try:
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    for it in articles_map.values():
                        cur.execute("""
                            INSERT INTO articles (url, canonical_url, source, source_name, region, country, language, category, title, description, author, content_markdown, content_html, renderer)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (url) DO UPDATE SET
                                title = EXCLUDED.title,
                                description = EXCLUDED.description,
                                author = EXCLUDED.author,
                                content_markdown = EXCLUDED.content_markdown,
                                content_html = EXCLUDED.content_html,
                                renderer = EXCLUDED.renderer;
                        """, (
                            it.get("url"), it.get("canonical_url"), it.get("source"), it.get("source_name"),
                            it.get("region"), it.get("country"), it.get("language"), it.get("category"),
                            it.get("title"), it.get("description"), it.get("author"),
                            it.get("content_markdown"), it.get("content_html"), it.get("renderer")
                        ))
                    conn.commit()
            print("PostgreSQL updated successfully!")
        except Exception as e:
            print(f"PostgreSQL update error: {e}")

if __name__ == "__main__":
    run_repair()
