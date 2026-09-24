import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


class JsonLinesPipeline:
    def open_spider(self, spider):
        self.path = Path(os.getenv("OUTPUT_FILE", "/data/articles.jsonl"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = self.path.open("a", encoding="utf-8")

    def close_spider(self, spider):
        self.fp.close()

    def process_item(self, item, spider):
        row = dict(item)
        self.fp.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self.fp.flush()
        return item


class PostgresPipeline:
    def open_spider(self, spider):
        enabled = os.getenv("ENABLE_POSTGRES", "true").lower() in {"1", "true", "yes", "on"}
        self.enabled = enabled
        self.conn = None
        if not enabled:
            spider.logger.info("Postgres pipeline disabled")
            return

        self.conn = psycopg.connect(os.environ["DATABASE_URL"])
        self.conn.autocommit = True
        # Keep an existing MVP database compatible even when the Postgres
        # docker-entrypoint init scripts are not re-run for an existing volume.
        with self.conn.cursor() as cur:
            cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS country VARCHAR(64)")
            cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS category VARCHAR(64)")
            cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS canonical_url TEXT")

    def close_spider(self, spider):
        if self.conn:
            self.conn.close()

    def process_item(self, item, spider):
        if not self.enabled or not self.conn:
            return item

        row = dict(item)
        sql = """
        INSERT INTO articles (
            source, source_name, region, country, language, category, url, canonical_url, title, description, author,
            published_at, content_markdown, content_html,
            discovery_method, renderer, discovered_at, raw_data
        ) VALUES (
            %(source)s, %(source_name)s, %(region)s, %(country)s, %(language)s, %(category)s, %(url)s, %(canonical_url)s, %(title)s,
            %(description)s, %(author)s, %(published_at)s,
            %(content_markdown)s, %(content_html)s,
            %(discovery_method)s, %(renderer)s, %(discovered_at)s, %(raw_data)s
        )
        ON CONFLICT (url) DO UPDATE SET
            source = EXCLUDED.source,
            source_name = EXCLUDED.source_name,
            region = EXCLUDED.region,
            country = EXCLUDED.country,
            language = EXCLUDED.language,
            category = EXCLUDED.category,
            canonical_url = EXCLUDED.canonical_url,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            author = EXCLUDED.author,
            published_at = EXCLUDED.published_at,
            content_markdown = EXCLUDED.content_markdown,
            content_html = EXCLUDED.content_html,
            renderer = EXCLUDED.renderer,
            crawled_at = NOW(),
            raw_data = EXCLUDED.raw_data
        """
        params = {
            "source": row.get("source"),
            "source_name": row.get("source_name"),
            "region": row.get("region"),
            "country": row.get("country"),
            "language": row.get("language"),
            "category": row.get("category"),
            "url": row.get("url"),
            "canonical_url": row.get("canonical_url"),
            "title": row.get("title"),
            "description": row.get("description"),
            "author": row.get("author"),
            "published_at": row.get("published_at"),
            "content_markdown": row.get("content_markdown"),
            "content_html": row.get("content_html"),
            "discovery_method": row.get("discovery_method"),
            "renderer": row.get("renderer"),
            "discovered_at": row.get("discovered_at"),
            "raw_data": Jsonb(row.get("raw_data") or {}),
        }
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
        return item
