# Changelog - v2 multi-source

- Expanded from 3 to 46 configured finance/news sources.
- 14 Vietnam sources, 32 international sources.
- Added `rss`, `html`, and `sitemap` discovery modes to the generic spider.
- Added source filters: `sources=...`, `regions=VN|GLOBAL`, and `max_items=N`.
- Added Scrapy static article renderer beside Crawl4AI browser renderer.
- Added `country`, `category`, and `canonical_url` fields.
- Added runtime PostgreSQL migration for existing MVP volumes.
- Added region runner, source smoke test, source listing, and stronger project validation.
- Removed macOS `__MACOSX` metadata from the package.
