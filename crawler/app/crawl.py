"""Pipeline crawl CHUNG cho mọi website, điều khiển hoàn toàn bởi config/sites.yaml.

Bước 1  iter_listing_pages : crawl trang chuyên mục -> JsonCssExtractionStrategy (schema sinh từ YAML)
                         -> link bài (+ ngày đăng nếu listing có) theo từng khối, phân trang `url` hoặc `click`,
                         trả về TỪNG TRANG để bên gọi dừng sớm khi đã qua khoảng ngày cần lấy
Bước 2  lọc link đã có trong DB (trừ khi --force) / ngoài khoảng ngày
Bước 3  crawl_articles : arun_many (song song, có rate limit) -> mỗi bài:
          - JsonCssExtractionStrategy (raw html)  -> metadata theo thứ tự: selector site > JSON-LD > meta mặc định
          - target_elements + excluded_selector   -> cleaned_html chỉ chứa khung nội dung
          - DefaultMarkdownGenerator              -> markdown của khung nội dung
Bước 4  upsert vào PostgreSQL
"""

from __future__ import annotations

import html as htmllib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlsplit

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    JsonCssExtractionStrategy,
    MemoryAdaptiveDispatcher,
    RateLimiter,
    UndetectedAdapter,
)
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy

from .site_config import ARTICLE_FIELDS, SiteConfig, coalesce, coalesce_tags

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Cấu hình Crawl4AI
# ---------------------------------------------------------------------------
def build_crawler(site: SiteConfig, headless: bool = True) -> AsyncWebCrawler:
    """Mỗi site có thể có cấu hình browser riêng (stealth, undetected, proxy, header...)."""
    b = site.browser
    extra = {k: b[k] for k in ("cdp_url", "proxy_config", "user_data_dir") if b.get(k)}
    browser_cfg = BrowserConfig(
        browser_type="chromium",
        headless=b.get("headless", headless),
        text_mode=b.get("text_mode", True),        # chặn tải ảnh/font -> nhanh hơn
        enable_stealth=b.get("enable_stealth", True),
        viewport_width=1366,
        viewport_height=900,
        user_agent=b.get("user_agent", DEFAULT_UA),
        headers=b.get("headers") or {},
        verbose=False,
        **extra,
    )
    if b.get("undetected"):
        # patchright-based adapter: vượt được một số cơ chế phát hiện automation
        strategy = AsyncPlaywrightCrawlerStrategy(browser_config=browser_cfg, browser_adapter=UndetectedAdapter())
        return AsyncWebCrawler(crawler_strategy=strategy, config=browser_cfg)
    return AsyncWebCrawler(config=browser_cfg)


def build_listing_config(site: SiteConfig) -> CrawlerRunConfig:
    return CrawlerRunConfig(
        extraction_strategy=JsonCssExtractionStrategy(site.listing_schema()),
        cache_mode=CacheMode.BYPASS,       # luôn lấy bản mới nhất của trang chuyên mục
        wait_until="domcontentloaded",
        wait_for=site.listing_wait_for,    # chờ tới khi các item tin đã có trong DOM
        page_timeout=60_000,
        verbose=False,
    )


def build_article_config(site: SiteConfig) -> CrawlerRunConfig:
    return CrawlerRunConfig(
        # metadata -> chạy trên raw html nên đọc được cả <meta>, JSON-LD trong <head>
        extraction_strategy=JsonCssExtractionStrategy(site.article_schema()),
        # LƯU Ý: dùng target_elements, KHÔNG dùng css_selector. Ở crawl4ai 0.8.x, css_selector cắt
        # HTML ngay trong trình duyệt -> extraction_strategy mất <head>, tác giả, ngày đăng, tags.
        # target_elements chỉ tác động tới markdown/cleaned_html, extraction vẫn thấy toàn trang.
        target_elements=[site.content_selector],
        excluded_selector=", ".join(site.exclude),
        excluded_tags=["script", "style", "noscript", "iframe", "form"],
        word_count_threshold=1,            # giữ cả đoạn ngắn (chú thích, số liệu)
        markdown_generator=DefaultMarkdownGenerator(
            options={"ignore_links": True, "body_width": 0, "escape_html": False}
        ),
        cache_mode=CacheMode.BYPASS,
        wait_until="domcontentloaded",
        wait_for=site.article_wait_for,
        page_timeout=60_000,
        stream=True,                       # arun_many trả về từng kết quả ngay khi xong
        verbose=False,
    )


# JS bấm nút phân trang / "Xem thêm" rồi chờ danh sách item thay đổi.
# Crawl4AI chạy đoạn này trên trang đang mở (session_id + js_only), sau đó chờ `wait_for`.
_CLICK_JS = """
(() => {
  window.__c4aPageDone = false;
  const btnSel = __BTN__, itemSel = __ITEMS__;
  const links = () => Array.from(document.querySelectorAll(itemSel))
      .map(e => { const a = e.querySelector('a[href]'); return a ? a.getAttribute('href') : ''; })
      .filter(Boolean);                      // bỏ qua skeleton/placeholder chưa có link
  const before = links(), beforeSig = before.join('|');
  const btn = document.querySelector(btnSel);
  if (!btn) { window.__c4aPageDone = true; return; }
  btn.scrollIntoView({block: 'center'});
  btn.click();
  let n = 0;
  const t = setInterval(() => {
    n++;
    const now = links();
    // "Xem thêm": danh sách dài ra; phân trang số: danh sách đổi nội dung. Không tính lúc đang bị xoá tạm.
    const changed = now.join('|') !== beforeSig && now.length >= before.length;
    if (changed || n > 75) {
      clearInterval(t);
      setTimeout(() => { window.__c4aPageDone = true; }, 600);   // chờ DOM ổn định
    }
  }, 200);
})();
"""


def _click_js(site: SiteConfig, page: int) -> str:
    btn = site.pagination["selector"].replace("{page}", str(page))
    return _CLICK_JS.replace("__BTN__", json.dumps(btn)).replace("__ITEMS__", json.dumps(site.all_items_selector))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(eq=False)
class ListingItem:
    url: str
    title: str
    section: str                 # tên khối trong config (featured | stream | ...)
    listing_url: str
    sapo: Optional[str] = None
    thumbnail_url: Optional[str] = None
    # ngày đăng: lấy từ trang listing nếu có, sau đó được cập nhật bằng ngày trong DB / trong bài
    published_at: Optional[datetime] = None


@dataclass
class CrawlStats:
    links_found: int = 0
    links_new: int = 0
    saved: int = 0
    failed: int = 0
    skipped: int = 0             # crawl rồi nhưng ngày đăng nằm ngoài khoảng ngày cần lấy
    errors: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Bước 1: lấy link bài từ trang chuyên mục
# ---------------------------------------------------------------------------
def _parse_listing(result, site: SiteConfig, listing_url: str, blocks: Optional[set[str]]) -> list[ListingItem]:
    data = (json.loads(result.extracted_content or "[]") or [{}])[0]
    items: list[ListingItem] = []
    for block in site.blocks:                     # giữ thứ tự khối như trong YAML
        if blocks and block not in blocks:
            continue
        for row in data.get(block) or []:
            url = site.normalize_url(coalesce(row, "href"))
            if not url:
                continue
            items.append(ListingItem(
                url=url,
                title=coalesce(row, "title") or "",
                section=block,
                listing_url=listing_url,
                sapo=coalesce(row, "sapo"),
                thumbnail_url=coalesce(row, "thumbnail_url"),
                published_at=site.parse_datetime(coalesce(row, "published_at")),
            ))
    return items


async def iter_listing_pages(
    crawler: AsyncWebCrawler,
    site: SiteConfig,
    listing_url: str,
    max_pages: int = 1,
    blocks: Optional[set[str]] = None,
) -> AsyncIterator[tuple[int, str, list[ListingItem]]]:
    """Yield (số trang, url trang, các link MỚI của trang đó) - lần lượt từng trang.

    Bên gọi `break` lúc nào cũng được; nên bọc bằng contextlib.aclosing() để session click được đóng ngay.
    """
    config = build_listing_config(site)
    mode = site.pagination.get("type") if max_pages > 1 else None
    session_id = f"listing-{site.key}-{uuid.uuid4().hex[:8]}" if mode == "click" else None
    seen: set[str] = set()

    def fresh(new_items: list[ListingItem]) -> list[ListingItem]:
        out = []
        for it in new_items:
            if it.url not in seen:
                seen.add(it.url)
                out.append(it)
        return out

    try:
        result = await crawler.arun(url=listing_url, config=config.clone(session_id=session_id))
        if not result.success:
            raise RuntimeError(f"Không crawl được {listing_url}: {result.error_message}")
        page_items = fresh(_parse_listing(result, site, listing_url, blocks))
        log.info("[%s] trang 1: %d link (%s)", site.key, len(page_items), listing_url)
        yield 1, listing_url, page_items

        for page in range(2, max_pages + 1 if mode else 2):
            if mode == "url":
                page_url = site.page_url(listing_url, result.html, page)
                if not page_url:
                    log.warning("[%s] không dựng được URL trang %d, dừng phân trang", site.key, page)
                    break
                r = await crawler.arun(url=page_url, config=config)
            else:  # click
                page_url = f"{listing_url} (click #{page})"
                # Thứ tự trong crawl4ai 0.8.x: js_code_before_wait -> wait_for -> js_code.
                # Phải bấm nút ở js_code_before_wait thì wait_for mới "thấy" được kết quả.
                r = await crawler.arun(url=listing_url, config=config.clone(
                    session_id=session_id, js_only=True, js_code_before_wait=_click_js(site, page),
                    wait_for="js:() => window.__c4aPageDone === true", wait_for_timeout=20_000,
                ))
            if not r.success:
                log.warning("[%s] trang %d lỗi: %s", site.key, page, r.error_message)
                break
            page_items = fresh(_parse_listing(r, site, listing_url, blocks))
            log.info("[%s] trang %d: +%d link mới (%s)", site.key, page, len(page_items), page_url)
            if not page_items:
                log.info("[%s] không còn link mới, dừng phân trang", site.key)
                break
            yield page, page_url, page_items
    finally:
        if session_id:
            await crawler.crawler_strategy.kill_session(session_id)


async def discover_links(
    crawler: AsyncWebCrawler,
    site: SiteConfig,
    listing_url: str,
    pages: int = 1,
    blocks: Optional[set[str]] = None,
) -> list[ListingItem]:
    """Gom link của `pages` trang đầu (không lọc theo ngày)."""
    items: list[ListingItem] = []
    async for _, _, page_items in iter_listing_pages(crawler, site, listing_url, max_pages=pages, blocks=blocks):
        items += page_items
    return items


# ---------------------------------------------------------------------------
# Bước 3: crawl nội dung từng bài
# ---------------------------------------------------------------------------
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_MARKUP = re.compile(r"(^#{1,6}\s*|^\s*[-*+>]\s+|\*\*|__|`)", re.MULTILINE)
_ARTICLE_TYPES = {"NewsArticle", "Article", "ReportageNewsArticle", "AnalysisNewsArticle", "BlogPosting"}


def markdown_to_text(md: str) -> str:
    text = _MD_IMAGE.sub("", md)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_MARKUP.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _names(value: Any) -> Optional[str]:
    """author/publisher trong JSON-LD: str | {name} | [{name}, ...]"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name")
    if isinstance(value, list):
        return ", ".join(n for n in (_names(v) for v in value) if n) or None
    return None


def extract_json_ld(raw_html: str) -> dict[str, Any]:
    """Đọc schema.org NewsArticle (hầu hết báo điện tử đều có) -> fallback metadata chung."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw_html or "", re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = set(types) if isinstance(types, list) else {types}
            if not types & _ARTICLE_TYPES:
                continue
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            if isinstance(image, dict):
                image = image.get("url")
            keywords = node.get("keywords")
            if isinstance(keywords, str):
                keywords = [k.strip() for k in keywords.split(",")]
            out = {
                "title": node.get("headline"),
                "sapo": node.get("description"),
                "author": _names(node.get("author")),
                "published_at": node.get("datePublished"),
                "category": node.get("articleSection") if isinstance(node.get("articleSection"), str) else None,
                "thumbnail_url": image,
                "tags": [k for k in (keywords or []) if k],
            }
            return {k: (htmllib.unescape(v).strip() if isinstance(v, str) else v) for k, v in out.items() if v}
    return {}


def _external_id(url: str) -> Optional[str]:
    ids = re.findall(r"\d{5,}", urlsplit(url).path)
    return ids[-1] if ids else None


def parse_article(result, site: SiteConfig, item: ListingItem) -> dict:
    row = (json.loads(result.extracted_content or "[]") or [{}])[0]
    ld = extract_json_ld(result.html)

    def pick(name: str) -> Optional[str]:
        # Ưu tiên: selector riêng của site > JSON-LD > selector mặc định (meta)
        return coalesce(row, f"site.{name}") or ld.get(name) or coalesce(row, f"default.{name}")

    meta = {name: pick(name) for name in ARTICLE_FIELDS}

    published_at = None
    for cand in (coalesce(row, "site.published_at"), ld.get("published_at"), coalesce(row, "default.published_at")):
        if (published_at := site.parse_datetime(cand)):
            break

    tags = coalesce_tags(row, "site.tags") or ld.get("tags") or coalesce_tags(row, "default.tags")

    markdown = (result.markdown.raw_markdown if result.markdown else "") or ""
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    content_text = markdown_to_text(markdown)

    return {
        "source": site.key,
        "external_id": _external_id(item.url),
        "url": item.url,
        "canonical_url": meta["canonical_url"],
        "category": meta["category"],
        "title": meta["title"] or item.title,
        "sapo": meta["sapo"] or item.sapo,
        "author": meta["author"],
        "original_source": meta["original_source"],
        "published_at": published_at,
        "thumbnail_url": meta["thumbnail_url"] or item.thumbnail_url,
        "tags": list(dict.fromkeys(tags or [])),
        "content_text": content_text,
        "content_markdown": markdown,
        "content_html": result.cleaned_html,
        "word_count": len(content_text.split()),
        "listing_url": item.listing_url,
        "listing_section": item.section,
        "http_status": result.status_code,
    }


async def crawl_articles(
    crawler: AsyncWebCrawler,
    site: SiteConfig,
    items: list[ListingItem],
    concurrency: int = 3,
    min_words: Optional[int] = None,
) -> AsyncIterator[tuple[ListingItem, Optional[dict], Optional[str]]]:
    """Yield (item, article | None, error | None) cho từng bài, ngay khi crawl xong."""
    if not items:
        return
    min_words = site.min_words if min_words is None else min_words
    by_url = {it.url: it for it in items}
    dispatcher = MemoryAdaptiveDispatcher(
        max_session_permit=concurrency,      # số tab chạy song song tối đa
        memory_threshold_percent=85.0,       # RAM vượt ngưỡng -> tạm dừng mở tab mới
        rate_limiter=RateLimiter(
            base_delay=(1.0, 2.5),           # nghỉ ngẫu nhiên giữa các request cùng domain
            max_delay=30.0,
            max_retries=2,
            rate_limit_codes=[429, 503],     # gặp mã này -> backoff rồi thử lại
        ),
    )

    async for result in await crawler.arun_many(
        urls=list(by_url), config=build_article_config(site), dispatcher=dispatcher
    ):
        item = by_url.get(result.url) or by_url.get(site.normalize_url(result.url) or "")
        if item is None:
            log.warning("Kết quả không khớp URL nào: %s", result.url)
            continue
        if not result.success:
            yield item, None, f"crawl failed ({result.status_code}): {result.error_message}"
            continue
        try:
            article = parse_article(result, site, item)
        except Exception as exc:  # noqa: BLE001
            yield item, None, f"parse error: {exc!r}"
            continue
        if article["word_count"] < min_words:
            yield item, None, (
                f"nội dung quá ngắn ({article['word_count']} từ) - bố cục khác article.content "
                f"'{site.content_selector}', hoặc một selector trong exclude đang khớp thẻ cha của nội dung"
            )
            continue
        yield item, article, None
