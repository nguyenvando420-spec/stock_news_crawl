"""PostgreSQL layer (psycopg 3, async)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
# trong image: /opt/crawler/init-db.sql ; chạy từ repo: <root>/init-db.sql
SCHEMA_FILE = next((p for p in (_HERE.parent / "init-db.sql", _HERE.parent.parent / "init-db.sql") if p.exists()),
                   _HERE.parent / "init-db.sql")

ARTICLE_COLUMNS = [
    "source", "external_id", "url", "canonical_url", "category", "title", "sapo",
    "author", "original_source", "published_at", "thumbnail_url", "tags",
    "content_text", "content_markdown", "content_html", "word_count",
    "listing_url", "listing_section", "http_status",
]

_UPSERT_SQL = f"""
INSERT INTO articles ({", ".join(ARTICLE_COLUMNS)})
VALUES ({", ".join(f"%({c})s" for c in ARTICLE_COLUMNS)})
ON CONFLICT (url) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in ARTICLE_COLUMNS if c not in ("url", "listing_url", "listing_section"))},
    updated_at = now()
RETURNING id, (xmax = 0) AS inserted
"""


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn: psycopg.AsyncConnection | None = None

    async def __aenter__(self) -> "Database":
        self.conn = await psycopg.AsyncConnection.connect(self.dsn, autocommit=True, row_factory=dict_row)
        await self.ensure_schema()
        return self

    async def __aexit__(self, *exc) -> None:
        if self.conn:
            await self.conn.close()

    async def ensure_schema(self) -> None:
        if SCHEMA_FILE.exists():
            await self.conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    # ---------------- articles ----------------
    async def existing_urls(self, urls: Iterable[str]) -> set[str]:
        urls = list(urls)
        if not urls:
            return set()
        cur = await self.conn.execute("SELECT url FROM articles WHERE url = ANY(%s)", (urls,))
        return {row["url"] for row in await cur.fetchall()}

    async def published_dates(self, urls: Iterable[str]) -> dict[str, Optional[datetime]]:
        """{url: published_at} của các url ĐÃ có trong DB."""
        urls = list(urls)
        if not urls:
            return {}
        cur = await self.conn.execute("SELECT url, published_at FROM articles WHERE url = ANY(%s)", (urls,))
        return {row["url"]: row["published_at"] for row in await cur.fetchall()}

    async def upsert_article(self, article: dict[str, Any]) -> tuple[int, bool]:
        row = {c: article.get(c) for c in ARTICLE_COLUMNS}
        row["tags"] = row["tags"] or []
        cur = await self.conn.execute(_UPSERT_SQL, row)
        res = await cur.fetchone()
        return res["id"], res["inserted"]

    # ---------------- crawl runs ----------------
    async def start_run(self, source: str, listing_url: str,
                        target_from: Optional[date] = None, target_to: Optional[date] = None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO crawl_runs (source, listing_url, target_from, target_to) VALUES (%s, %s, %s, %s) RETURNING id",
            (source, listing_url, target_from, target_to),
        )
        return (await cur.fetchone())["id"]

    async def finish_run(self, run_id: int, *, status: str, links_found: int, links_new: int,
                         saved: int, failed: int, errors: list[dict], skipped: int = 0) -> None:
        await self.conn.execute(
            """UPDATE crawl_runs
               SET finished_at = now(), status = %s, links_found = %s, links_new = %s,
                   saved = %s, failed = %s, skipped = %s, errors = %s::jsonb
               WHERE id = %s""",
            (status, links_found, links_new, saved, failed, skipped,
             json.dumps(errors, ensure_ascii=False), run_id),
        )
