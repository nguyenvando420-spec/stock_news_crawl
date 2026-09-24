import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from dateutil import parser as date_parser
import feedparser
import scrapy
import yaml

from crawler.items import ArticleItem
from crawler.extractor import extract_article_data, clean_title, clean_description, clean_text


class NewsSpider(scrapy.Spider):
    name = "news"

    def __init__(self, sources="all", regions="all", enrich="auto", max_items=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sources_arg = sources
        self.regions_arg = regions
        self.enrich_arg = enrich.lower()
        self.max_items_override = int(max_items) if max_items else None
        sources_path = os.getenv("SOURCES_FILE", "/config/sources.yaml")
        with open(sources_path, "r", encoding="utf-8") as fp:
            cfg = yaml.safe_load(fp) or {}
        self.sources = cfg.get("sources", {})

    def start_requests(self):
        selected = self._selected_sources()
        self.logger.info("Selected %d configured sources", len(selected))
        for source_id, cfg in selected.items():
            if not cfg.get("enabled", True):
                continue
            discovery = cfg.get("discovery", "rss")
            url = cfg.get("feed_url") if discovery == "rss" else cfg.get("start_url") or cfg.get("sitemap_url")
            if not url:
                self.logger.warning("Skipping %s: no discovery URL", source_id)
                continue
            callback = {"rss": self.parse_feed, "html": self.parse_listing, "sitemap": self.parse_sitemap}.get(discovery)
            if not callback:
                self.logger.warning("Skipping %s: unsupported discovery=%s", source_id, discovery)
                continue
            headers = {"Accept": "*/*", **(cfg.get("headers") or {})}
            yield scrapy.Request(url, callback=callback, cb_kwargs={"source_id": source_id, "cfg": cfg}, headers=headers, dont_filter=True)

    def parse_feed(self, response, source_id, cfg):
        feed = feedparser.parse(response.body)
        if getattr(feed, "bozo", False):
            self.logger.warning("Feed parse warning for %s: %s", source_id, getattr(feed, "bozo_exception", "unknown"))
        entries = list(feed.entries)[: self._limit(cfg)]
        self.logger.info("%s: discovered %d RSS items", source_id, len(entries))
        for entry in entries:
            link = entry.get("link")
            if not link:
                continue
            seed = self._seed(source_id, cfg, link, "rss")
            seed.update({
                "title": clean_title(self._text(entry.get("title"))),
                "description": clean_description(self._text(entry.get("summary") or entry.get("description"))),
                "author": clean_text(self._text(entry.get("author"))),
                "published_at": self._published(entry),
                "raw_data": {"feed_url": cfg.get("feed_url"), "entry_id": entry.get("id"), "tags": [t.get("term") for t in entry.get("tags", []) if isinstance(t, dict)]},
            })
            yield from self._article_requests(seed, cfg)

    def parse_listing(self, response, source_id, cfg):
        selector = cfg.get("link_selector", "a::attr(href)")
        values = response.css(selector).getall()
        pattern = re.compile(cfg.get("include_regex", r".+"))
        exclude = re.compile(cfg.get("exclude_regex", r"$^"))
        seen = set()
        count = 0
        for value in values:
            if not value:
                continue
            url = response.urljoin(value.strip())
            if url in seen or not pattern.search(url) or exclude.search(url):
                continue
            if cfg.get("same_domain", True) and urlparse(url).netloc != urlparse(response.url).netloc:
                continue
            seen.add(url)
            seed = self._seed(source_id, cfg, url, "html")
            yield from self._article_requests(seed, cfg)
            count += 1
            if count >= self._limit(cfg):
                break
        self.logger.info("%s: discovered %d HTML listing items", source_id, count)

    def parse_sitemap(self, response, source_id, cfg):
        try:
            root = ET.fromstring(response.body)
        except ET.ParseError as exc:
            self.logger.warning("Invalid sitemap for %s: %s", source_id, exc)
            return
        locs = [x.text.strip() for x in root.iter() if x.tag.endswith("loc") and x.text]
        pattern = re.compile(cfg.get("include_regex", r".+"))
        count = 0
        for url in locs:
            if not pattern.search(url):
                continue
            seed = self._seed(source_id, cfg, url, "sitemap")
            yield from self._article_requests(seed, cfg)
            count += 1
            if count >= self._limit(cfg):
                break
        self.logger.info("%s: discovered %d sitemap items", source_id, count)

    def _article_requests(self, seed, cfg):
        if not self._should_enrich(cfg):
            yield ArticleItem(**seed)
            return
        renderer = cfg.get("renderer", "crawl4ai")
        meta = {"source_cfg": cfg, "handle_httpstatus_all": True}
        if renderer == "crawl4ai":
            meta["use_crawl4ai"] = True
        headers = {"Accept": "*/*", **(cfg.get("headers") or {})}
        yield scrapy.Request(seed["url"], headers=headers, callback=self.parse_article, cb_kwargs={"seed": seed, "cfg": cfg}, meta=meta, dont_filter=False)

    def parse_article(self, response, seed, cfg):
        raw_extra = {}
        if response.meta.get("use_crawl4ai"):
            payload = response.meta.get("crawl4ai_payload") or {}
            metadata = payload.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            raw_extra = {
                "crawl4ai_success": payload.get("success"),
                "crawl4ai_status_code": payload.get("status_code"),
                "crawl4ai_error": response.meta.get("crawl4ai_error"),
                "crawl4ai_metadata": metadata,
            }
        else:
            raw_extra = {"http_status": getattr(response, "status", None)}

        html_content = getattr(response, "text", "") or ""

        from crawler.extractor import is_cloudflare_challenge
        is_blocked = response.status in (403, 503) or is_cloudflare_challenge(html_content)

        used_cdp = False
        if is_blocked:
            self.logger.warning("Article blocked or challenge detected for %s (status=%s)", seed["url"], getattr(response, "status", None))
            try:
                from crawler.cdp import is_cdp_available, fetch_via_cdp
                if is_cdp_available():
                    self.logger.info("Attempting Cloudflare bypass via CDP for %s", seed["url"])
                    cdp_html = fetch_via_cdp(seed["url"], timeout=18)
                    if cdp_html and not is_cloudflare_challenge(cdp_html):
                        self.logger.info("Successfully bypassed Cloudflare via CDP for %s", seed["url"])
                        html_content = cdp_html
                        used_cdp = True
                        raw_extra["bypassed_via_cdp"] = True
            except Exception as e:
                self.logger.warning("CDP bypass error: %s", e)

        extracted = extract_article_data(html_content, cfg, seed)

        if not used_cdp and (not extracted.get("content_markdown") or len(extracted.get("content_markdown", "").strip()) < 50):
            try:
                from crawler.cdp import is_cdp_available, fetch_via_cdp
                if is_cdp_available():
                    self.logger.info("Content empty or unrendered, attempting CDP fallback for %s", seed["url"])
                    cdp_html = fetch_via_cdp(seed["url"], timeout=18)
                    if cdp_html and not is_cloudflare_challenge(cdp_html):
                        self.logger.info("Successfully fetched article via CDP fallback for %s", seed["url"])
                        html_content = cdp_html
                        used_cdp = True
                        raw_extra["bypassed_via_cdp"] = True
                        extracted = extract_article_data(html_content, cfg, seed)
            except Exception as e:
                self.logger.warning("CDP fallback error: %s", e)

        seed["title"] = extracted.get("title") or seed.get("title")
        seed["description"] = extracted.get("description") or seed.get("description")
        seed["author"] = extracted.get("author") or seed.get("author")
        seed["canonical_url"] = extracted.get("canonical_url") or seed.get("url")
        seed["content_markdown"] = extracted.get("content_markdown")
        seed["content_html"] = extracted.get("content_html")
        seed["renderer"] = "cdp" if used_cdp else cfg.get("renderer", "scrapy")
        seed["raw_data"] = {**(seed.get("raw_data") or {}), **raw_extra}

        yield ArticleItem(**seed)

    def _seed(self, source_id, cfg, url, discovery_method):
        return {
            "source": source_id, "source_name": cfg.get("name", source_id), "region": cfg.get("region"), "country": cfg.get("country"),
            "language": cfg.get("language"), "category": cfg.get("category", "finance"), "url": url, "canonical_url": url,
            "title": None, "description": None, "author": None, "published_at": None, "content_markdown": None, "content_html": None,
            "discovery_method": discovery_method, "renderer": "discovery-only", "discovered_at": datetime.now(timezone.utc).isoformat(), "raw_data": {},
        }

    def _selected_sources(self):
        rows = self.sources
        if self.sources_arg != "all":
            wanted = {x.strip() for x in self.sources_arg.split(",") if x.strip()}
            rows = {k: v for k, v in rows.items() if k in wanted}
        if self.regions_arg != "all":
            wanted_regions = {x.strip().upper() for x in self.regions_arg.split(",") if x.strip()}
            rows = {k: v for k, v in rows.items() if str(v.get("region", "")).upper() in wanted_regions}
        return rows

    def _limit(self, cfg):
        return self.max_items_override or int(cfg.get("max_items", 5))

    def _should_enrich(self, cfg):
        if self.enrich_arg in {"false", "0", "no", "off"}: return False
        if self.enrich_arg in {"true", "1", "yes", "on"}: return True
        return bool(cfg.get("enrich_article", True))

    @staticmethod
    def _published(entry):
        for key in ("published", "updated", "created"):
            value = entry.get(key)
            if value:
                try:
                    dt = date_parser.parse(value)
                    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                    return dt.isoformat()
                except Exception: pass
        return None

    @staticmethod
    def _text(value):
        return str(value).strip() if value is not None else None

    @staticmethod
    def _first_text(values):
        for value in values:
            value = re.sub(r"\s+", " ", value or "").strip()
            if value: return value
        return None
