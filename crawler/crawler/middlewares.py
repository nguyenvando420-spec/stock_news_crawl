import json
import os
import re
import time
from typing import Any

import httpx
from scrapy import signals
from scrapy.http import HtmlResponse
from twisted.internet.threads import deferToThread


class Crawl4AIMiddleware:
    def __init__(self, crawler=None):
        self.crawler = crawler
        self.base_url = os.getenv("CRAWL4AI_URL", "http://crawl4ai:11235").rstrip("/")
        self.api_token = os.getenv("CRAWL4AI_API_TOKEN", "")
        self.timeout = float(os.getenv("CRAWL4AI_TIMEOUT", "120"))
        self.client = None

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def spider_opened(self, spider):
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        self.client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        )

    def spider_closed(self, spider):
        if self.client:
            self.client.close()
            self.client = None

    def process_request(self, request, spider):
        if not request.meta.get("use_crawl4ai"):
            return None
        return deferToThread(self._crawl, request, spider)

    def _crawl(self, request, spider):
        source_cfg = request.meta.get("source_cfg") or {}
        selectors = source_cfg.get("selectors") or {}

        wait_until = source_cfg.get("wait_until", "domcontentloaded")
        delay_html = float(source_cfg.get("delay_before_return_html", 0.5))
        wait_for = source_cfg.get("wait_for")

        crawler_params = {
            "stream": False,
            "cache_mode": "bypass",
            "wait_until": wait_until,
            "delay_before_return_html": delay_html,
            "page_timeout": 30000,
            "magic": True,
            "simulate_user": True,
            "override_navigator": True,
            "remove_overlay_elements": True,
            "excluded_tags": ["nav", "footer", "aside", "script", "style", "noscript", "iframe", "form"],
        }
        if wait_for:
            crawler_params["wait_for"] = wait_for

        payload = {
            "urls": [request.url],
            "browser_config": {
                "type": "BrowserConfig",
                "params": {
                    "headless": True,
                    "verbose": False,
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "viewport_width": 1440,
                    "viewport_height": 900,
                },
            },
            "crawler_config": {
                "type": "CrawlerRunConfig",
                "params": crawler_params,
            },
        }

        data = None
        for attempt in range(1, 3):
            try:
                if self.client:
                    resp = self.client.post("/crawl", json=payload)
                else:
                    headers = {"Content-Type": "application/json"}
                    if self.api_token:
                        headers["Authorization"] = f"Bearer {self.api_token}"
                    with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                        resp = client.post(
                            f"{self.base_url}/crawl",
                            headers=headers,
                            json=payload,
                        )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:
                if attempt == 2:
                    spider.logger.warning("Crawl4AI failed for %s: %s", request.url, exc)
                    request.meta["crawl4ai_error"] = repr(exc)
                    # Attempt CDP bypass on error
                    from crawler.cdp import is_cdp_available, fetch_via_cdp
                    if is_cdp_available():
                        spider.logger.info("Attempting CDP fallback for failed Crawl4AI request: %s", request.url)
                        cdp_html = fetch_via_cdp(request.url, timeout=18)
                        if cdp_html:
                            return HtmlResponse(
                                url=request.url,
                                request=request,
                                status=200,
                                body=cdp_html.encode("utf-8", errors="replace"),
                                encoding="utf-8",
                            )
                    return HtmlResponse(
                        url=request.url,
                        request=request,
                        status=599,
                        body=b"",
                        encoding="utf-8",
                    )
                time.sleep(1.0)

        result = self._first_result(data)
        request.meta["crawl4ai_payload"] = result
        request.meta["crawl4ai_raw"] = data

        html = (
            result.get("html")
            or result.get("cleaned_html")
            or result.get("fit_html")
            or ""
        )

        from crawler.extractor import is_cloudflare_challenge
        is_empty_or_challenge = (
            is_cloudflare_challenge(html)
            or len(html.strip()) < 150
            or ("crawl4ai-result" in html and len(html.strip()) < 200)
        )
        if is_empty_or_challenge:
            spider.logger.warning("Empty or Cloudflare challenge page returned by Crawl4AI for %s", request.url)
            from crawler.cdp import is_cdp_available, fetch_via_cdp
            if is_cdp_available():
                spider.logger.info("Bypassing Cloudflare challenge via CDP for %s", request.url)
                cdp_html = fetch_via_cdp(request.url, timeout=18)
                if cdp_html and not is_cloudflare_challenge(cdp_html):
                    html = cdp_html

        return HtmlResponse(
            url=result.get("url") or request.url,
            request=request,
            status=200 if result.get("success", True) else 599,
            body=html.encode("utf-8", errors="replace"),
            encoding="utf-8",
        )

    @staticmethod
    def _first_result(data: Any) -> dict:
        if isinstance(data, dict):
            for key in ("results", "result", "data"):
                value = data.get(key)
                if isinstance(value, list) and value:
                    return value[0] if isinstance(value[0], dict) else {"value": value[0]}
                if isinstance(value, dict):
                    return value
            return data
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else {"value": data[0]}
        return {"raw": json.dumps(data, ensure_ascii=False)}
