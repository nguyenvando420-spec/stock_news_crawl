# Stock News Crawler v2 - 46 sources

MVP duoc mo rong tu ban goc Scrapy + Crawl4AI + PostgreSQL de crawl **46 nguon tin tai chinh**: **14 Viet Nam + 32 quoc te**.

## Kien truc

```text
RSS / HTML listing / Sitemap
          |
        Scrapy
          |
    article URLs
       /      \
 Scrapy       Crawl4AI
 static        browser
       \      /
       normalized Article
          |
   JSONL + PostgreSQL
```

Spider la generic: them nguon chu yeu bang `config/sources.yaml`, khong can tao spider rieng.

## 1. Chay nhanh

```bash
cp .env.example .env
# nen thay token bang: openssl rand -hex 32

docker compose build
docker compose up -d postgres crawl4ai
```

Smoke test tat ca nguon, chi lay 1 link/nguon va khong enrich:

```bash
./scripts/smoke_test_sources.sh all
```

Smoke test rieng Viet Nam:

```bash
./scripts/smoke_test_sources.sh VN
```

## 2. Crawl Viet Nam

```bash
./scripts/run_region.sh VN auto 5
```

- `VN`: region
- `auto`: dung `enrich_article` cua tung source
- `5`: toi da 5 bai moi/nguon moi lan chay

## 3. Crawl quoc te

```bash
./scripts/run_region.sh GLOBAL auto 5
```

## 4. Crawl tat ca 46 nguon

```bash
./scripts/run_full.sh
```

Hoac de giam tai khi test:

```bash
docker compose --profile run run --rm crawler \
  scrapy crawl news -a enrich=false -a max_items=2
```

## 5. Crawl mot vai nguon

```bash
docker compose --profile run run --rm crawler \
  scrapy crawl news \
  -a sources=cafef_stock,vneconomy_stocks,vietstock_stocks,reuters_business,cnbc_business \
  -a max_items=5
```

## 6. Danh sach nguon

```bash
python scripts/list_sources.py
```

Cau hinh hien tai co:

- 14 nguon Viet Nam
- 32 nguon quoc te
- 39 RSS feeds
- 7 HTML listing sources

Nhom Viet Nam gom CafeF, VnExpress, VnEconomy, Vietstock, Bao Dau Tu, Thanh Nien, Tuoi Tre, Dan Tri, VietnamPlus, VTV, Viet Nam News, VOV, VietNamNet, Nhan Dan.

Nhom quoc te gom Investing.com, CNBC, MarketWatch, Nasdaq, BBC, The Guardian, Reuters, Financial Times, CoinDesk, Cointelegraph, Benzinga, Finextra, PYMNTS, Seeking Alpha, Fed, ECB, SEC, Bank of England, IMF, Nikkei Asia, CNA, Straits Times, Business Times Singapore, Economic Times, LiveMint, Moneycontrol, Japan Times, SCMP, ABC Australia, Yahoo Finance Taiwan, TechCrunch va Business Standard.

> Feed URL, HTML va dieu khoan cua cac website co the thay doi. Hay chay `smoke_test_sources.sh` dinh ky; crawler duoc thiet ke de mot source loi khong lam dung toan bo cac source con lai.

## 7. Them/sua source

RSS:

```yaml
my_feed:
  enabled: true
  name: My Finance Feed
  region: GLOBAL
  country: US
  language: en
  category: markets
  discovery: rss
  feed_url: https://example.com/feed.xml
  max_items: 5
  enrich_article: true
  renderer: crawl4ai
  selectors:
    title: "h1.title::text, h1::text"
    description: ".sapo::text, p.description::text"
    content: ".article-content, article"
    author: ".author::text"
    remove: ".ad-banner, .relate-container, .social-share, .tags"
```

HTML listing:

```yaml
my_site:
  enabled: true
  name: My Site
  region: GLOBAL
  country: US
  language: en
  category: business
  discovery: html
  start_url: https://example.com/business
  link_selector: 'a::attr(href)'
  include_regex: 'https?://example\\.com/business/.+'
  max_items: 5
  enrich_article: true
  renderer: crawl4ai
  selectors:
    title: "h1::text"
    description: "meta[name=\"description\"]::attr(content)"
    content: "main article"
    remove: ".ads, .sidebar, .related"
```

### Các trường trong block `selectors`:
- `title`: CSS selector lấy tiêu đề bài viết (tự động lọc sạch đuôi tên báo như `- Báo VnExpress`, `| CafeF`).
- `description`: CSS selector lấy đoạn tóm tắt / sapo (tự động loại bỏ các thẻ `<img>`, `<a>` rác).
- `content`: CSS selector chỉ định chính xác khung chứa nội dung bài viết.
- `author`: CSS selector lấy tên tác giả bài viết.
- `remove`: Danh sách các class/id rác cần loại bỏ triệt để (quảng cáo, bài đọc thêm, box chia sẻ, banner...).

*Lưu ý: Nếu một source không khai báo `selectors`, crawler sẽ tự động kích hoạt **Smart Fallback** để tự động nhận diện bài viết và loại bỏ các phần tử rác thông dụng.*

## 8. Renderer

`renderer: scrapy` dung HTTP Scrapy de lay article, nhe hon va phu hop HTML tinh.

`renderer: crawl4ai` goi browser service Crawl4AI, phu hop trang JS-heavy, anti-bot nhe, lazy rendering.

Khi scale 30-50 sources, nen crawl theo region/batch thay vi mo browser cho tat ca cung luc.

## 9. Output

JSONL:

```text
output/articles.jsonl
```

PostgreSQL:

```bash
./scripts/show_db.sh
```

Schema them `country`, `category`, `canonical_url`. `init.sql` co `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, nen co the dung lai DB volume cua MVP cu.

## 10. Kiem tra source nao co ket qua

Sau smoke test:

```bash
python - <<'PY'
import json
from collections import Counter
p='output/smoke_all.jsonl'
c=Counter(json.loads(x)['source'] for x in open(p, encoding='utf-8') if x.strip())
for k,v in sorted(c.items()): print(k, v)
print('sources returned:', len(c))
PY
```

Neu mot source khong tra ket qua, xem log cua Scrapy va kiem tra feed/listing URL trong `config/sources.yaml`.

## 11. Luu y van hanh

- Khong nen crawl full 46 source voi 20-50 article/source ngay tu dau.
- Bat dau voi 3-5 article/source, sau do tang dan.
- Ton trong robots.txt/Terms/licensing cua tung nha xuat ban; RSS cua mot so bao chi ro chi cho muc dich ca nhan/phi thuong mai.
- Cac trang paywall co the discovery duoc title/link nhung content day du co the khong truy cap duoc.
- Neu dung production, pin version Docker image va them scheduler/queue/metrics.
