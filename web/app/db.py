"""Database connection and query layer for the web portal."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from datetime import datetime, date

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("web.db")

SOURCE_CONFIGS = {
    "cafef": {
        "id": "cafef",
        "name": "CafeF",
        "color": "#2563eb",
        "badge_bg": "rgba(37, 99, 235, 0.15)",
        "badge_border": "rgba(37, 99, 235, 0.35)",
        "url": "https://cafef.vn",
    },
    "vietstock": {
        "id": "vietstock",
        "name": "Vietstock",
        "color": "#ea580c",
        "badge_bg": "rgba(234, 88, 12, 0.15)",
        "badge_border": "rgba(234, 88, 12, 0.35)",
        "url": "https://vietstock.vn",
    },
    "nguoiquansat": {
        "id": "nguoiquansat",
        "name": "Người Quan Sát",
        "color": "#8b5cf6",
        "badge_bg": "rgba(139, 92, 246, 0.15)",
        "badge_border": "rgba(139, 92, 246, 0.35)",
        "url": "https://nguoiquansat.vn",
    },
    "tinnhanhchungkhoan": {
        "id": "tinnhanhchungkhoan",
        "name": "Tin Nhanh Chứng Khoán",
        "color": "#06b6d4",
        "badge_bg": "rgba(6, 182, 212, 0.15)",
        "badge_border": "rgba(6, 182, 212, 0.35)",
        "url": "https://tinnhanhchungkhoan.vn",
    },
}


class DatabaseManager:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        if self.pool is None:
            self.pool = AsyncConnectionPool(
                conninfo=self.dsn,
                min_size=2,
                max_size=10,
                kwargs={"row_factory": dict_row, "autocommit": True},
            )
            await self.pool.open()
            log.info("Database pool opened successfully.")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None
            log.info("Database pool closed.")

    async def get_stats(self) -> dict[str, Any]:
        """Lấy thống kê tổng quan về bài viết và crawl runs."""
        assert self.pool is not None, "Pool chưa được khởi tạo"
        async with self.pool.connection() as conn:
            cur = await conn.execute("""
                SELECT
                    count(*) AS total_articles,
                    count(*) FILTER (WHERE published_at >= (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) AS today_articles,
                    count(*) FILTER (WHERE crawled_at > now() - interval '24 hours') AS last_24h_crawled,
                    max(crawled_at) AS latest_crawled_at
                FROM articles;
            """)
            summary = await cur.fetchone() or {}

            cur = await conn.execute("""
                SELECT source, count(*) as count
                FROM articles
                GROUP BY source
                ORDER BY count DESC;
            """)
            sources = await cur.fetchall()

            cur = await conn.execute("""
                SELECT id, source, started_at, status, links_found, saved, failed
                FROM crawl_runs
                ORDER BY id DESC
                LIMIT 5;
            """)
            recent_runs = await cur.fetchall()

            return {
                "total_articles": summary.get("total_articles", 0),
                "today_articles": summary.get("today_articles", 0),
                "last_24h_crawled": summary.get("last_24h_crawled", 0),
                "latest_crawled_at": summary.get("latest_crawled_at"),
                "sources_count": {r["source"]: r["count"] for r in sources},
                "recent_runs": recent_runs,
            }

    async def get_sources_meta(self) -> list[dict[str, Any]]:
        """Lấy danh sách các nguồn báo kèm thông tin cấu hình và số lượng bài."""
        assert self.pool is not None, "Pool chưa được khởi tạo"
        async with self.pool.connection() as conn:
            cur = await conn.execute("""
                SELECT source, count(*) as article_count
                FROM articles
                GROUP BY source;
            """)
            rows = await cur.fetchall()
            counts = {r["source"]: r["article_count"] for r in rows}

        results = []
        for s_id, cfg in SOURCE_CONFIGS.items():
            results.append({
                **cfg,
                "count": counts.get(s_id, 0),
            })
        return results

    async def get_articles(
        self,
        page: int = 1,
        page_size: int = 12,
        source: Optional[str] = None,
        q: Optional[str] = None,
        date_filter: Optional[str] = None,
        category: Optional[str] = None,
    ) -> dict[str, Any]:
        """Truy vấn danh sách bài viết có phân trang và bộ lọc."""
        assert self.pool is not None, "Pool chưa được khởi tạo"
        page = max(1, page)
        page_size = min(max(1, page_size), 50)
        offset = (page - 1) * page_size

        where_clauses = ["1=1"]
        params: list[Any] = []

        if source and source in SOURCE_CONFIGS:
            where_clauses.append("source = %s")
            params.append(source)

        if category:
            where_clauses.append("category = %s")
            params.append(category)

        if q and q.strip():
            search_term = f"%{q.strip()}%"
            exact_tag = q.strip()
            where_clauses.append("(title ILIKE %s OR sapo ILIKE %s OR %s = ANY(tags))")
            params.extend([search_term, search_term, exact_tag])

        if date_filter:
            if date_filter == "today":
                where_clauses.append("published_at >= (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date")
            elif date_filter == "3days":
                where_clauses.append("published_at >= now() - interval '3 days'")
            elif date_filter == "7days":
                where_clauses.append("published_at >= now() - interval '7 days'")
            else:
                # Thử parse ngày cụ thể YYYY-MM-DD
                try:
                    date.fromisoformat(date_filter)
                    where_clauses.append("published_at::date = %s")
                    params.append(date_filter)
                except ValueError:
                    pass

        where_sql = " AND ".join(where_clauses)

        async with self.pool.connection() as conn:
            # Đếm tổng số bản ghi
            count_sql = f"SELECT count(*) as total FROM articles WHERE {where_sql};"
            cur = await conn.execute(count_sql, params)
            total_row = await cur.fetchone()
            total = total_row["total"] if total_row else 0

            # Lấy danh sách bài viết
            data_sql = f"""
                SELECT
                    id, source, external_id, url, canonical_url,
                    category, title, sapo, author, original_source,
                    published_at, thumbnail_url, tags, word_count,
                    listing_section, crawled_at
                FROM articles
                WHERE {where_sql}
                ORDER BY published_at DESC NULLS LAST, id DESC
                LIMIT %s OFFSET %s;
            """
            cur = await conn.execute(data_sql, [*params, page_size, offset])
            rows = await cur.fetchall()

        # Bổ sung metadata nguồn cho từng bài
        for r in rows:
            src_cfg = SOURCE_CONFIGS.get(r["source"], {})
            r["source_name"] = src_cfg.get("name", r["source"].capitalize())
            r["source_color"] = src_cfg.get("color", "#64748b")
            r["source_badge_bg"] = src_cfg.get("badge_bg", "rgba(100, 116, 139, 0.15)")
            r["source_badge_border"] = src_cfg.get("badge_border", "rgba(100, 116, 139, 0.35)")

        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

    async def get_article_detail(self, article_id: int) -> Optional[dict[str, Any]]:
        """Lấy toàn bộ nội dung chi tiết bài viết kèm bài trước / sau."""
        assert self.pool is not None, "Pool chưa được khởi tạo"
        async with self.pool.connection() as conn:
            cur = await conn.execute("""
                SELECT *
                FROM articles
                WHERE id = %s;
            """, (article_id,))
            article = await cur.fetchone()
            if not article:
                return None

            # Bổ sung thông tin nguồn
            src_cfg = SOURCE_CONFIGS.get(article["source"], {})
            article["source_name"] = src_cfg.get("name", article["source"].capitalize())
            article["source_color"] = src_cfg.get("color", "#64748b")
            article["source_badge_bg"] = src_cfg.get("badge_bg", "rgba(100, 116, 139, 0.15)")
            article["source_badge_border"] = src_cfg.get("badge_border", "rgba(100, 116, 139, 0.35)")

            # Lấy 3 bài liên quan cùng nguồn hoặc cùng chuyên mục
            cur = await conn.execute("""
                SELECT id, source, title, published_at, thumbnail_url, category
                FROM articles
                WHERE id <> %s AND (source = %s OR category = %s)
                ORDER BY published_at DESC NULLS LAST, id DESC
                LIMIT 4;
            """, (article_id, article["source"], article.get("category")))
            related = await cur.fetchall()
            for rel in related:
                rel_cfg = SOURCE_CONFIGS.get(rel["source"], {})
                rel["source_name"] = rel_cfg.get("name", rel["source"].capitalize())
                rel["source_color"] = rel_cfg.get("color", "#64748b")
            article["related"] = related

            return article
