#!/usr/bin/env python3
"""
Re-clean all previously crawled articles using the new DOMExtractor and source selectors.
Updates both output/articles.jsonl and PostgreSQL database.
"""

import os
import sys
import json
import yaml
from pathlib import Path

# Add crawler directory to path
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/app")
sys.path.insert(0, str(root_dir / "crawler"))

from crawler.extractor import extract_article_data, clean_title, clean_description, clean_text

def reclean():
    sources_file = os.getenv("SOURCES_FILE", str(root_dir / "config" / "sources.yaml"))
    with open(sources_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    sources_cfg = cfg.get("sources", {})

    jsonl_path = Path(os.getenv("OUTPUT_FILE", str(root_dir / "output" / "articles.jsonl")))
    if not jsonl_path.exists():
        print(f"File not found: {jsonl_path}")
        return

    print(f"Reading {jsonl_path}...")
    articles_map = {}
    total_raw = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_raw += 1
            try:
                item = json.loads(line)
                url = item.get("url")
                if url:
                    articles_map[url] = item
            except Exception:
                pass

    print(f"Found {total_raw} records ({len(articles_map)} unique URLs). Re-cleaning DOM and Markdown...")

    cleaned_articles = []
    cleaned_count = 0

    for url, item in articles_map.items():
        source_id = item.get("source")
        source_config = sources_cfg.get(source_id, {})
        html_content = item.get("content_html")

        if html_content and html_content.strip():
            extracted = extract_article_data(html_content, source_config, item)
            item["title"] = extracted.get("title") or clean_title(item.get("title"))
            item["description"] = extracted.get("description") or clean_description(item.get("description"))
            item["author"] = extracted.get("author") or clean_text(item.get("author"))
            item["canonical_url"] = extracted.get("canonical_url") or item.get("url")
            item["content_markdown"] = extracted.get("content_markdown") or item.get("content_markdown")
            if extracted.get("content_html"):
                item["content_html"] = extracted.get("content_html")
            cleaned_count += 1
        else:
            item["title"] = clean_title(item.get("title"))
            item["description"] = clean_description(item.get("description"))
            item["author"] = clean_text(item.get("author"))

        cleaned_articles.append(item)

    # Sort descending by published_at
    cleaned_articles.sort(key=lambda x: x.get("published_at") or x.get("discovered_at") or "", reverse=True)

    # Backup original file
    backup_path = jsonl_path.with_suffix(".jsonl.bak")
    if not backup_path.exists():
        import shutil
        shutil.copyfile(jsonl_path, backup_path)
        print(f"Created backup at {backup_path}")

    # Write cleaned articles back to jsonl
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for a in cleaned_articles:
            f.write(json.dumps(a, ensure_ascii=False, default=str) + "\n")

    print(f"✅ Successfully cleaned and saved {len(cleaned_articles)} articles to {jsonl_path} ({cleaned_count} re-parsed with DOM selectors).")

    # Update PostgreSQL if available
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            import psycopg
            print("Connecting to PostgreSQL to update articles...")
            with psycopg.connect(db_url) as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    for a in cleaned_articles:
                        cur.execute(
                            """
                            UPDATE articles
                            SET title = %(title)s,
                                description = %(description)s,
                                author = %(author)s,
                                content_markdown = %(content_markdown)s,
                                canonical_url = %(canonical_url)s
                            WHERE url = %(url)s;
                            """,
                            a,
                        )
            print("✅ PostgreSQL updated successfully!")
        except Exception as e:
            print(f"⚠️ Could not update PostgreSQL: {e}")

if __name__ == "__main__":
    reclean()
