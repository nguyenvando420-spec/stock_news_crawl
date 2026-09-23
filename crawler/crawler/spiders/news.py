import os
from datetime import datetime, timezone
from dateutil import parser as date_parser
import feedparser
import scrapy
import yaml

from crawler.items import ArticleItem


class NewsSpider(scrapy.Spider):
    name = "news"

    def __init__(self, sources="all", enrich="auto", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sources_arg = sources
        self.enrich_arg = enrich.lower()
        sources_path = os.getenv("SOURCES_FILE", "/config/sources.yaml")
        with open(sources_path, "r", encoding="utf-8") as fp:
            cfg = yaml.safe_load(fp) or {}
        self.sources = cfg.get("sources", {})

    def start_requests(self):
        selected = self._selected_sources()
        for source_id, cfg in selected.items():
            if not cfg.get("enabled", True):
                continue
            if cfg.get("discovery") != "rss":
                self.logger.warning("Skipping %s: only discovery=rss is supported in MVP", source_id)
                continue
            yield scrapy.Request(
                cfg["feed_url"],
                callback=self.parse_feed,
                cb_kwargs={"source_id": source_id, "cfg": cfg},
                headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"},
                dont_filter=True,
            )

    def parse_feed(self, response, source_id, cfg):
        feed = feedparser.parse(response.body)
        if getattr(feed, "bozo", False):
            self.logger.warning("Feed parse warning for %s: %s", source_id, getattr(feed, "bozo_exception", "unknown"))

        limit = int(cfg.get("max_items", 10))
        entries = list(feed.entries)[:limit]
        self.logger.info("%s: discovered %d feed items", source_id, len(entries))

        for entry in entries:
            link = entry.get("link")
            if not link:
                continue

            seed = {
                "source": source_id,
                "source_name": cfg.get("name", source_id),
                "region": cfg.get("region"),
                "language": cfg.get("language"),
                "url": link,
                "title": self._text(entry.get("title")),
                "description": self._text(entry.get("summary") or entry.get("description")),
                "author": self._text(entry.get("author")),
                "published_at": self._published(entry),
                "content_markdown": None,
                "content_html": None,
                "discovery_method": "rss",
                "renderer": "rss-only",
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                "raw_data": {
                    "feed_url": cfg.get("feed_url"),
                    "entry_id": entry.get("id"),
                    "tags": [t.get("term") for t in entry.get("tags", []) if isinstance(t, dict)],
                },
            }

            if self._should_enrich(cfg):
                yield scrapy.Request(
                    link,
                    callback=self.parse_article,
                    cb_kwargs={"seed": seed, "cfg": cfg},
                    meta={"use_crawl4ai": True, "handle_httpstatus_all": True},
                )
            else:
                yield ArticleItem(**seed)

    def parse_article(self, response, seed, cfg):
        payload = response.meta.get("crawl4ai_payload") or {}
        raw = response.meta.get("crawl4ai_raw") or {}

        markdown = payload.get("markdown")
        if isinstance(markdown, dict):
            markdown = markdown.get("raw_markdown") or markdown.get("fit_markdown") or str(markdown)

        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        seed["title"] = metadata.get("title") or seed.get("title")
        seed["description"] = metadata.get("description") or seed.get("description")
        seed["author"] = metadata.get("author") or seed.get("author")
        seed["content_markdown"] = markdown
        seed["content_html"] = payload.get("cleaned_html") or payload.get("fit_html") or payload.get("html")
        seed["renderer"] = cfg.get("renderer", "crawl4ai")
        seed["raw_data"] = {
            **(seed.get("raw_data") or {}),
            "crawl4ai_success": payload.get("success"),
            "crawl4ai_status_code": payload.get("status_code"),
            "crawl4ai_error": response.meta.get("crawl4ai_error"),
            "crawl4ai_metadata": metadata,
        }
        yield ArticleItem(**seed)

    def _selected_sources(self):
        if self.sources_arg == "all":
            return self.sources
        wanted = {x.strip() for x in self.sources_arg.split(",") if x.strip()}
        return {k: v for k, v in self.sources.items() if k in wanted}

    def _should_enrich(self, cfg):
        if self.enrich_arg in {"false", "0", "no", "off"}:
            return False
        if self.enrich_arg in {"true", "1", "yes", "on"}:
            return True
        return bool(cfg.get("enrich_article", True))

    @staticmethod
    def _published(entry):
        for key in ("published", "updated", "created"):
            value = entry.get(key)
            if not value:
                continue
            try:
                dt = date_parser.parse(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
        for key in ("published_parsed", "updated_parsed", "created_parsed"):
            val_tuple = entry.get(key)
            if val_tuple:
                try:
                    dt = datetime(*val_tuple[:6], tzinfo=timezone.utc)
                    return dt.isoformat()
                except Exception:
                    pass
        return None

    @staticmethod
    def _text(value):
        if value is None:
            return None
        return str(value).strip()
