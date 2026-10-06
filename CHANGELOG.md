# Changelog

## v3.2 - Crawl theo ngày đăng

- Job định kỳ (`docker compose up -d`) = `--today --interval-minutes 10`: chỉ lưu bài đăng hôm nay, bỏ URL đã có.
- Dữ liệu lịch sử chạy tay: `--date YYYY-MM-DD` hoặc `--from A --to B`; tự phân trang lùi tới khi qua mốc ngày (`--max-pages`).
- `listing.item.published_at` trong YAML: lọc theo ngày ngay ở trang listing, không cần mở bài.
- Site không có ngày ở listing: crawl bài cuối trang trước để định vị trang theo thời gian.
- Parse thêm thời gian tương đối ("8 phút trước", "1h trước", "hôm qua 20:30") và ngày thiếu năm ("05/10 20:30").
- `crawl_runs` có thêm `target_from`, `target_to`, `skipped` (tự migrate bằng `ALTER ... IF NOT EXISTS`).
- Chu kỳ tính từ lúc bắt đầu mỗi lần chạy; service `restart: unless-stopped`, tắt HEALTHCHECK kế thừa từ image gốc.

## v3.1 - Config-driven multi-site

- Toàn bộ kiến thức riêng của từng site chuyển vào `config/sites.yaml` (mount vào container); xoá `app/sites/*.py`.
- Thêm Vietstock, Tin nhanh chứng khoán, Người Quan Sát; Reuters có cấu hình nhưng tắt (DataDome 401).
- Selector mini-language (`css`, `css@attr`, danh sách ưu tiên) biên dịch sang `JsonCssExtractionStrategy`.
- Fallback metadata từ JSON-LD `NewsArticle`.
- Phân trang `click` (session_id + js_only + js_code_before_wait) bên cạnh phân trang `url`.
- Cấu hình browser theo site (`undetected`, header, proxy...).
- Bỏ service `crawl4ai-playground`: stack chỉ còn `postgres` + `crawler` (dùng Crawl4AI SDK trực tiếp).

## v3 - Crawl4AI + PostgreSQL only

- Bỏ Scrapy, n8n, Firecrawl: pipeline chỉ còn Crawl4AI 0.8.6 (Python SDK) + PostgreSQL 16.
- Crawler image build từ `unclecode/crawl4ai:0.8.6` (có sẵn Chromium/Playwright).
- Lấy link từ vùng nội dung chính của trang chuyên mục CafeF (featured + stream, bỏ "Đọc nhiều"),
  hỗ trợ phân trang AJAX `/timelinelist/{zone}/{page}.chn`.
- Metadata bài viết qua `JsonCssExtractionStrategy`; nội dung qua `target_elements` + `excluded_selector` + markdown.
- Crawl song song bằng `arun_many` + `MemoryAdaptiveDispatcher` + `RateLimiter`, lưu từng bài ngay khi xong.
- Schema mới: `articles` (UPSERT theo url, tags TEXT[]) và `crawl_runs` (nhật ký + lỗi JSONB).
- Kiến trúc `SiteProfile` để thêm website mới chỉ bằng khai báo selector.

## v2 - multi-source (Scrapy)

- Expanded from 3 to 46 configured finance/news sources.
- 14 Vietnam sources, 32 international sources.
- Added `rss`, `html`, and `sitemap` discovery modes to the generic spider.
- Added source filters: `sources=...`, `regions=VN|GLOBAL`, and `max_items=N`.
- Added Scrapy static article renderer beside Crawl4AI browser renderer.
- Added `country`, `category`, and `canonical_url` fields.
- Added runtime PostgreSQL migration for existing MVP volumes.
- Added region runner, source smoke test, source listing, and stronger project validation.
- Removed macOS `__MACOSX` metadata from the package.
