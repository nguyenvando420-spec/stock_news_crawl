# Stock News Crawler: Crawl4AI + PostgreSQL

Crawl tin tức tài chính chỉ bằng **[Crawl4AI](https://github.com/unclecode/crawl4ai) 0.8.6** (Python SDK, Chromium headless) và lưu vào **PostgreSQL**.
**Mỗi website chỉ là một khối cấu hình trong [`config/sites.yaml`](config/sites.yaml)**, không cần viết code Python cho từng site.

| Site | Trang chuyên mục | Khối lấy link | Phân trang | Trạng thái |
|---|---|---|---|---|
| `cafef` | cafef.vn/thi-truong-chung-khoan.chn | featured + stream | `url` (AJAX `/timelinelist/{zone}/{page}.chn`) | ✅ |
| `vietstock` | vietstock.vn/chung-khoan.htm | stream | `click` (nút số trang JS) | ✅ |
| `tinnhanhchungkhoan` | tinnhanhchungkhoan.vn/chung-khoan/ | featured + stream | `click` ("Xem thêm") | ✅ |
| `nguoiquansat` | nguoiquansat.vn/chung-khoan | featured + stream | `click` ("Xem thêm") | ✅ |
| `reuters` | reuters.com/business/ | stream | – | ⛔ tắt: DataDome chặn (HTTP 401) |

```text
 config/sites.yaml ──► site_config.py (biên dịch selector -> schema Crawl4AI)
                                │
 Trang chuyên mục ── crawler.arun() + JsonCssExtractionStrategy(listing schema)
        │  [+ trang 2..N: URL template, hoặc bấm nút trong cùng session (session_id + js_only)]
        ▼
 Link bài theo khối (featured/stream), lọc bằng article_url_pattern, bỏ link đã có trong DB
        ▼
 crawler.arun_many()  ── MemoryAdaptiveDispatcher + RateLimiter
        │   ├─ JsonCssExtractionStrategy(article schema) ─┐
        │   ├─ JSON-LD NewsArticle trong trang ──────────┼─► metadata (ưu tiên: site > JSON-LD > meta mặc định)
        │   ├─ target_elements + excluded_selector        -> cleaned_html chỉ khung nội dung
        │   └─ DefaultMarkdownGenerator                   -> content_markdown -> content_text
        ▼
 PostgreSQL: articles (UPSERT theo url) + crawl_runs
```

## Cấu trúc thư mục

```text
.
├── config/sites.yaml          # ★ cấu hình TẤT CẢ website (mount vào container)
├── docker-compose.yaml        # postgres + crawler + web portal
├── init-db.sql                # schema: articles, crawl_runs
├── crawler/
│   ├── Dockerfile             # FROM unclecode/crawl4ai:0.8.6 (+ psycopg)
│   └── app/
│       ├── __main__.py        # CLI
│       ├── site_config.py     # nạp YAML, biên dịch selector -> JsonCss schema, parse ngày
│       ├── window.py          # khoảng ngày cần lấy (hôm nay / ngày / khoảng ngày)
│       ├── crawl.py           # pipeline Crawl4AI chung cho mọi site
│       └── db.py              # PostgreSQL (psycopg 3 async)
├── web/                       # ★ Giao diện Web Portal (FastAPI + Modern UI)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py            # API FastAPI & Route điều khiển
│       ├── db.py              # Pool kết nối & query PostgreSQL
│       ├── static/            # CSS Design System & JS tương tác
│       └── templates/         # Giao diện HTML5 (Dark/Light mode, Reader modal)
└── scripts/show_db.sh
```

## 1. Chạy nhanh

```bash
cp .env.example .env
docker compose up -d            # Chạy toàn bộ: postgres + crawler + web portal
docker compose logs -f crawler

# Mở trình duyệt xem tin tức trực tiếp:
# 👉 http://localhost:8000

# Dữ liệu lịch sử: chạy tay, truyền ngày (tự phân trang lùi tới khi qua mốc ngày)
docker compose run --rm crawler --date 2026-10-01                    # 1 ngày
docker compose run --rm crawler --from 2026-09-25 --to 2026-09-30    # khoảng ngày (bao gồm 2 đầu)
docker compose run --rm crawler --date 01/10/2026 --site cafef       # 1 site, ngày dạng DD/MM/YYYY

# Chạy 1 lần khác (truyền tham số sẽ ghi đè command mặc định nên không lặp)
docker compose run --rm crawler --list-sites                # các site trong config
docker compose run --rm crawler --dry-run --today           # xem trước link + ngày đăng (✓ trong / ✗ ngoài / ? chưa rõ)
docker compose run --rm crawler --today                     # bài hôm nay, 1 lần
docker compose run --rm crawler --interval-minutes 0        # không lọc ngày: trang 1, tối đa 30 bài mới/trang

./scripts/show_db.sh            # 20 bài mới nhất + lịch sử chạy
./scripts/show_db.sh 21         # chi tiết bài id=21
```

## 2. Tuỳ chọn CLI

| Tham số | Env | Mặc định | Ý nghĩa |
|---|---|---|---|
| `--today` | | (service compose: bật) | Chỉ bài đăng hôm nay (giờ VN) |
| `--date D` | | | Chỉ bài đăng ngày `D` (`YYYY-MM-DD` hoặc `DD/MM/YYYY`) |
| `--from A [--to B]` | | `B` = hôm nay | Bài đăng từ ngày `A` tới hết ngày `B` |
| `--max-pages N` | `CRAWL_MAX_PAGES` | 50 | Giới hạn an toàn số trang listing khi lọc theo ngày |
| `--site KEY` (lặp được) | `CRAWL_SITES` (csv) | mọi site enabled | Chọn site theo key trong YAML |
| `--url URL` (lặp được) | `CRAWL_URLS` (csv) | | URL chuyên mục bất kỳ, domain phải có trong YAML (vd `https://cafef.vn/doanh-nghiep.chn`) |
| `--pages N` | `CRAWL_PAGES` | 1 | Khi **không** lọc ngày: số trang listing (theo `pagination` của site) |
| `--max-articles N` | `CRAWL_MAX_ARTICLES` | 30 | Khi **không** lọc ngày: số bài **mới** tối đa mỗi trang chuyên mục (0 = không giới hạn) |
| `--concurrency N` | `CRAWL_CONCURRENCY` | 3 | Số tab Chromium song song |
| `--blocks a,b` | `CRAWL_BLOCKS` | tất cả | Chỉ lấy một số khối (vd `featured`) |
| `--min-words N` | | theo YAML | Ghi đè `min_words` |
| `--force` | | | Crawl lại cả bài đã có (UPSERT) |
| `--dry-run` | | | Chỉ in link (kèm ngày đăng nếu listing có) |
| `--interval-minutes N` | `CRAWL_INTERVAL_MINUTES` | 0 (CLI) / 10 (service compose) | > 0: chạy lặp mỗi N phút, tính từ lúc bắt đầu mỗi lần. Không dùng chung với `--date/--from` |
| `--config PATH` | `SITES_CONFIG` | `config/sites.yaml` | File cấu hình |

Chạy nền định kỳ: `docker compose up -d` (= `--today --interval-minutes 10`; đổi chu kỳ bằng `CRAWL_INTERVAL_MINUTES=15 docker compose up -d`).

### Lọc theo ngày hoạt động thế nào

1. Đi lần lượt từng trang listing (mới → cũ). Ngày đăng của mỗi link lấy từ: `listing.item.published_at` trong YAML → DB (bài đã lưu) → bộ nhớ tạm.
2. Link đã có trong DB hoặc biết chắc ngoài khoảng ngày → bỏ, không crawl.
3. Site không hiển thị ngày ở listing (vd Người Quan Sát): crawl trước **bài cuối trang** để biết trang đang ở mốc nào; nếu cả trang còn mới hơn khoảng cần lấy thì bỏ qua cả trang.
4. Sau khi crawl, ngày đăng trong bài là quyết định cuối: ngoài khoảng → **không lưu** (`skipped`).
5. Bài cũ nhất của trang đã trước ngày bắt đầu → dừng phân trang (giới hạn `--max-pages`).

> [!NOTE]
> Job `--today` lần đầu sau nửa đêm vẫn lấy nốt bài đăng trong `2 × chu kỳ` phút trước đó, để không sót bài đăng sát 0h.
> Mỗi lần chạy ghi `target_from`, `target_to`, `skipped` vào bảng `crawl_runs`.

## 3. Thêm website mới: chỉ sửa `config/sites.yaml`

```yaml
sites:
  my_site:
    name: My Site
    base_url: https://example.vn
    listing_urls: [https://example.vn/chung-khoan]
    article_url_pattern: '^https://example\.vn/[a-z0-9-]+-\d+\.html$'   # chỉ giữ link bài thật
    listing:
      blocks:                          # tên khối -> selector của TỪNG item tin (đừng chọn sidebar)
        featured: ".top-news .item"
        stream:   ".list-news .item"
      item:                            # (tuỳ chọn) ghi đè selector mặc định trong mỗi item
        title: ".title a"
    pagination:                        # (tuỳ chọn)
      type: click                      # click: bấm nút trong trình duyệt; url: dựng URL trang N
      selector: ".btn-load-more"       # có thể dùng {page}: "#paging a[page='{page}']"
    article:
      content: "div.article-body"      # khung nội dung chính
      exclude: [".ads", ".related"]    # rác bên trong khung nội dung
      fields:                          # (tuỳ chọn) - thiếu thì lấy từ JSON-LD rồi tới <meta>
        sapo: "p.sapo"
        tags: ".tags a"
```

Cú pháp selector:

| Viết | Nghĩa |
|---|---|
| `"h1.title"` | text của phần tử đầu tiên khớp |
| `"meta[property='og:image']@content"` | thuộc tính `content` |
| `"@href"` | thuộc tính của chính item |
| `["sel1", "sel2@attr"]` | danh sách **ưu tiên**: lấy giá trị đầu tiên khác rỗng |
| `tags: ".tags a"` / `tags: "meta[name=keywords]@content"` | list text mọi phần tử / 1 chuỗi tách dấu phẩy |

Metadata điền theo thứ tự: `article.fields` của site → **JSON-LD `NewsArticle`** → `defaults.article.fields` (thẻ `<meta>`). Vì hầu hết báo đều có JSON-LD, thường chỉ cần khai báo `content` và vài field như `sapo`, `tags`.

Quy trình thêm site:

```bash
# 1. sửa config/sites.yaml   2. kiểm tra link
docker compose run --rm crawler --site my_site --dry-run --pages 2
# 3. crawl thử vài bài rồi xem nội dung
docker compose run --rm crawler --site my_site --max-articles 3
./scripts/show_db.sh <id>
```

Không cần build lại image: `./config` được mount vào container.

## 4. Dữ liệu trong PostgreSQL

**`articles`**: `source` (key site), `external_id` (số cuối URL), `url` (unique), `canonical_url`, `category`, `title`, `sapo`, `author`, `original_source`, `published_at` (timestamptz), `thumbnail_url`, `tags` (TEXT[]), `content_text`, `content_markdown`, `content_html`, `word_count`, `listing_url`, `listing_section` (tên khối), `http_status`, `crawled_at`, `updated_at`.

**`crawl_runs`**: mỗi lần chạy mỗi trang chuyên mục: `links_found`, `links_new`, `saved`, `failed`, `errors` (JSONB).

```sql
SELECT source, count(*), max(published_at) FROM articles GROUP BY source;
SELECT id, source, published_at, title FROM articles
WHERE content_text ILIKE '%SHS%' ORDER BY published_at DESC;
```

## 5. Các thành phần Crawl4AI được dùng

| Thành phần | Dùng để |
|---|---|
| `AsyncWebCrawler`, `BrowserConfig` | 1 trình duyệt cho mỗi site; `text_mode`, `enable_stealth`, header, UA lấy từ `browser:` trong YAML |
| `UndetectedAdapter` + `AsyncPlaywrightCrawlerStrategy` | `browser.undetected: true` cho site có anti-bot |
| `CrawlerRunConfig` | Cấu hình từng lần crawl: `wait_for`, `cache_mode`, `page_timeout`... |
| `JsonCssExtractionStrategy` | Trích link (listing) và metadata (article) bằng CSS, **không cần LLM** |
| `target_elements` + `excluded_selector` | Markdown chỉ của khung nội dung, đã lọc rác |
| `DefaultMarkdownGenerator` | HTML → markdown |
| `session_id` + `js_only` + `js_code_before_wait` | Phân trang kiểu bấm nút trên **cùng một tab** |
| `arun_many` + `MemoryAdaptiveDispatcher` + `RateLimiter` | Crawl song song, giới hạn RAM, backoff 429/503 |

### Những lỗi dễ gặp với Crawl4AI 0.8.x (đã gặp khi làm dự án)

> [!IMPORTANT]
> **`css_selector` vs `target_elements`**: `css_selector` cắt HTML ngay trong trình duyệt, nên extraction mất `<head>`, JSON-LD, tác giả, ngày đăng. Dùng `target_elements` để chỉ giới hạn markdown.

> [!IMPORTANT]
> **Thứ tự chạy**: `js_code_before_wait` → `wait_for` → `js_code`. Muốn bấm nút rồi *chờ* kết quả thì phải dùng `js_code_before_wait`; đặt vào `js_code` thì `wait_for` chạy trước, chờ mãi rồi timeout.

> [!WARNING]
> **`excluded_selector` chạy trên toàn trang trước khi chọn khung nội dung.** Selector rộng như `[class*='banner']` khớp với thẻ cha `div.lr-banner-pos` của Vietstock và xoá mất cả bài. Hãy để `exclude` mặc định thật hẹp.

> [!TIP]
> Item nạp thêm qua "Xem thêm" có thể có markup khác trang 1 (TNCK: `h2` → `h3`). Nên dùng selector theo class (`.story__heading a`) thay vì theo thẻ.

### Reuters

Reuters dùng **DataDome**: Chromium headless, kể cả `UndetectedAdapter`, đều nhận HTTP 401 kèm captcha. Cấu hình vẫn có trong YAML nhưng `enabled: false`. Có thể thử `browser.cdp_url` trỏ tới Chrome thật của bạn hoặc dùng proxy, nhưng hãy kiểm tra điều khoản sử dụng của Reuters trước.

## 6. Lưu ý vận hành

- Giữ `--concurrency` thấp (2-4); tôn trọng robots.txt và điều khoản của từng báo.
- Bài có ít hơn `min_words` từ (video, infographic, bố cục lạ) bị ghi vào `crawl_runs.errors` và không làm dừng pipeline.
- Một site lỗi không làm dừng các site khác.
- Website đổi giao diện thì selector có thể hỏng. Nên chạy `--dry-run` định kỳ.
