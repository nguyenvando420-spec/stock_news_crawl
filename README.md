# Stock News MVP - Scrapy + Crawl4AI + PostgreSQL

MVP nay dung **Scrapy** de discovery tin tu RSS, **Crawl4AI** de render/boc noi dung bai viet, va **PostgreSQL + JSONL** de luu output.

## Nguon mau co san

- CafeF - Thi truong chung khoan: `https://cafef.vn/thi-truong-chung-khoan.rss`
- VnExpress - Kinh doanh: `https://vnexpress.net/rss/kinh-doanh.rss`
- Investing.com - Stock Market News: `https://www.investing.com/rss/news_25.rss`

> Luu y: RSS/website co the thay doi dieu khoan su dung. Neu dung thuong mai, hay kiem tra Terms/robots.txt cua tung nguon va gioi han tan suat crawl phu hop.

## 1. Yeu cau

- Docker Engine
- Docker Compose v2
- Khoang 4 GB RAM tro len (Chromium trong Crawl4AI ton RAM)

## 2. Chay nhanh

```bash
cp .env.example .env
```

Sua `.env` va dat token dai, vi du:

```bash
openssl rand -hex 32
```

Sau do:

```bash
./scripts/run_rss_only.sh
```

Che do nay chi discovery RSS, rat nhanh de xac nhan network/feed/output.

Output:

```bash
cat output/articles.jsonl
```

Xem PostgreSQL:

```bash
./scripts/show_db.sh
```

## 3. Chay full: RSS + Crawl4AI enrichment

```bash
./scripts/run_full.sh
```

Flow:

```text
RSS feed
  -> Scrapy parse feed
  -> article URL
  -> Crawl4AI /crawl
  -> title / description / markdown / cleaned_html
  -> JSONL + PostgreSQL
```

Crawl4AI playground:

```text
http://localhost:11235/playground
```

Health:

```bash
curl http://localhost:11235/health
```

## 4. Chay tung nguon

CafeF:

```bash
docker compose up -d postgres crawl4ai
docker compose --profile run run --rm crawler \
  scrapy crawl news -a sources=cafef_stock
```

VnExpress:

```bash
docker compose --profile run run --rm crawler \
  scrapy crawl news -a sources=vnexpress_business
```

Investing.com:

```bash
docker compose --profile run run --rm crawler \
  scrapy crawl news -a sources=investing_stock_market
```

Nhieu nguon:

```bash
docker compose --profile run run --rm crawler \
  scrapy crawl news -a sources=cafef_stock,vnexpress_business
```

Tat enrichment de chi test RSS:

```bash
docker compose --profile run run --rm crawler \
  scrapy crawl news -a enrich=false
```

## 5. Them website moi

Chi sua `config/sources.yaml`:

```yaml
sources:
  my_source:
    enabled: true
    name: My Finance Source
    region: GLOBAL
    language: en
    discovery: rss
    feed_url: https://example.com/feed.xml
    max_items: 10
    enrich_article: true
    renderer: crawl4ai
```

Khong can rebuild image vi `config/` duoc mount vao container.

## 6. Schema output JSONL

Moi dong la mot article:

```json
{
  "source": "cafef_stock",
  "region": "VN",
  "language": "vi",
  "url": "https://...",
  "title": "...",
  "description": "...",
  "author": "...",
  "published_at": "2026-09-23T15:45:00+07:00",
  "content_markdown": "...",
  "content_html": "...",
  "discovery_method": "rss",
  "renderer": "crawl4ai",
  "discovered_at": "...",
  "raw_data": {}
}
```

## 7. Kiem tra output mau

`output/sample_articles.jsonl` duoc kem de ban thay schema va ket qua mong doi. Mau nay duoc tao tu cac bai dang hien thi cong khai ngay 2026-09-23; khi ban chay MVP, `output/articles.jsonl` se chua tin moi tai thoi diem chay.

```bash
cat output/sample_articles.jsonl
```

## 8. Troubleshooting

### Crawl4AI 401

Dam bao `.env` co `CRAWL4AI_API_TOKEN` va crawler cung nhan cung token.

### Crawl4AI khoi dong cham

Lan dau pull image va warm Chromium co the cham. Xem log:

```bash
docker compose logs -f crawl4ai
```

### RSS bi 403

Mot so site co the chan datacenter IP/User-Agent. Thu chay tu IP khac, proxy hop le, hoac tat nguon do trong YAML.

### Chi muon verify feed truoc

```bash
./scripts/run_rss_only.sh
```

## 9. Dung he thong

```bash
docker compose down
```

Xoa ca DB volume neu muon reset hoan toan:

```bash
docker compose down -v
```
