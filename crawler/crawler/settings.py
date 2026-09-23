import os

BOT_NAME = "stock-news-mvp"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

ROBOTSTXT_OBEY = os.getenv("ROBOTSTXT_OBEY", "false").lower() in {"1", "true", "yes", "on"}
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
)

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}

CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 0.5
DOWNLOAD_TIMEOUT = 45
RETRY_ENABLED = True
RETRY_TIMES = 2

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

DOWNLOADER_MIDDLEWARES = {
    "crawler.middlewares.Crawl4AIMiddleware": 543,
}

ITEM_PIPELINES = {
    "crawler.pipelines.JsonLinesPipeline": 200,
    "crawler.pipelines.PostgresPipeline": 300,
}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
TELNETCONSOLE_ENABLED = False
