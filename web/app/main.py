"""FastAPI application entrypoint for VNStock News Portal."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import markdown
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import DatabaseManager, SOURCE_CONFIGS

APP_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:crawl4ai_password_2026@localhost:5433/news_db"
)

db_manager = DatabaseManager(DATABASE_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi động pool kết nối DB
    await db_manager.open()
    yield
    # Đóng pool
    await db_manager.close()


app = FastAPI(
    title="VNStock News Portal",
    description="Cổng tổng hợp tin tức thị trường chứng khoán Việt Nam trực tiếp từ PostgreSQL",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files và Templates
static_dir = APP_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# --- Helper Jinja Filters ---
VN_TZ = timezone(timedelta(hours=7))


def format_relative_time(dt: Optional[datetime]) -> str:
    """Định dạng thời gian theo phong cách tương đối tiếng Việt."""
    if not dt:
        return "Không rõ"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    diff = now - dt

    seconds = int(diff.total_seconds())
    if seconds < 0:
        return "Vừa xong"
    if seconds < 60:
        return f"{seconds} giây trước"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} phút trước"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} giờ trước"
    days = hours // 24
    if days == 1:
        return f"Hôm qua {dt.astimezone(VN_TZ).strftime('%H:%M')}"
    if days < 7:
        return f"{days} ngày trước"
    return dt.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")


def format_datetime_vn(dt: Optional[datetime], fmt: str = "%d/%m/%Y %H:%M") -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ).strftime(fmt)


templates.env.filters["relative_time"] = format_relative_time
templates.env.filters["datetime_vn"] = format_datetime_vn


# ========================================================
# REST API ENDPOINTS
# ========================================================

@app.get("/health")
async def health_check():
    """Kiểm tra sức khỏe dịch vụ."""
    return {"status": "ok", "timestamp": datetime.now(VN_TZ).isoformat()}


@app.get("/api/stats")
async def api_stats():
    """Lấy dữ liệu thống kê tổng hợp số lượng bài viết."""
    stats = await db_manager.get_stats()
    return jsonable_encoder(stats)


@app.get("/api/sources")
async def api_sources():
    """Lấy danh sách các nguồn báo và số lượng bài tương ứng."""
    sources = await db_manager.get_sources_meta()
    return jsonable_encoder(sources)


@app.get("/api/articles")
async def api_articles(
    page: int = Query(1, ge=1, description="Số trang"),
    page_size: int = Query(12, ge=1, le=50, description="Số bài mỗi trang"),
    source: Optional[str] = Query(None, description="Lọc theo nguồn (cafef, vietstock,...)"),
    q: Optional[str] = Query(None, description="Từ khóa tìm kiếm"),
    date: Optional[str] = Query(None, description="Bộ lọc ngày ('today', '3days', '7days', YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="Lọc theo chuyên mục"),
):
    """Lấy danh sách bài viết hỗ trợ tìm kiếm, lọc và phân trang."""
    data = await db_manager.get_articles(
        page=page,
        page_size=page_size,
        source=source,
        q=q,
        date_filter=date,
        category=category,
    )
    # Serialize datetime sang ISO string cho JSON
    for item in data["items"]:
        if item.get("published_at"):
            item["published_at_relative"] = format_relative_time(item["published_at"])
            item["published_at_formatted"] = format_datetime_vn(item["published_at"])

    return jsonable_encoder(data)


@app.get("/api/articles/{article_id}")
async def api_article_detail(article_id: int):
    """Lấy toàn bộ chi tiết bài viết (bao gồm nội dung HTML/Markdown)."""
    article = await db_manager.get_article_detail(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")

    if article.get("published_at"):
        article["published_at_relative"] = format_relative_time(article["published_at"])
        article["published_at_formatted"] = format_datetime_vn(article["published_at"])

    # Chuẩn bị HTML render từ markdown nếu content_html rỗng
    if not article.get("content_html") and article.get("content_markdown"):
        article["rendered_html"] = markdown.markdown(
            article["content_markdown"],
            extensions=["extra", "nl2br", "tables"]
        )
    else:
        article["rendered_html"] = article.get("content_html") or ""

    for rel in article.get("related", []):
        if rel.get("published_at"):
            rel["published_at_relative"] = format_relative_time(rel["published_at"])

    return jsonable_encoder(article)


# ========================================================
# WEB PAGES (Jinja2 HTML UI)
# ========================================================

@app.get("/", response_class=HTMLResponse)
async def home_page(
    request: Request,
    page: int = 1,
    source: Optional[str] = None,
    q: Optional[str] = None,
    date: Optional[str] = None,
):
    """Trang chủ hiển thị danh sách tin tức dạng card responsive."""
    stats = await db_manager.get_stats()
    sources = await db_manager.get_sources_meta()
    articles_data = await db_manager.get_articles(
        page=page,
        page_size=12,
        source=source,
        q=q,
        date_filter=date,
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "stats": stats,
            "sources": sources,
            "articles": articles_data["items"],
            "pagination": articles_data,
            "active_source": source,
            "active_q": q or "",
            "active_date": date or "",
            "source_configs": SOURCE_CONFIGS,
        },
    )


@app.get("/article/{article_id}", response_class=HTMLResponse)
async def article_page(request: Request, article_id: int):
    """Trang xem trực tiếp bài viết theo link riêng biệt (cho phép chia sẻ)."""
    article = await db_manager.get_article_detail(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")

    if not article.get("content_html") and article.get("content_markdown"):
        article["rendered_html"] = markdown.markdown(
            article["content_markdown"],
            extensions=["extra", "nl2br", "tables"]
        )
    else:
        article["rendered_html"] = article.get("content_html") or ""

    return templates.TemplateResponse(
        request=request,
        name="article.html",
        context={
            "article": article,
            "source_configs": SOURCE_CONFIGS,
        },
    )
