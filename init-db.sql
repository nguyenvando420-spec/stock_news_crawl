-- =========================================================
-- Schema cho pipeline Crawl4AI -> PostgreSQL
-- File này được Postgres tự chạy MỘT LẦN khi volume còn trống
-- (docker-entrypoint-initdb.d). Crawler cũng chạy lại file này
-- mỗi lần khởi động (idempotent) để đảm bảo schema luôn tồn tại.
-- =========================================================

-- Bài viết đã crawl (mỗi URL là 1 dòng duy nhất)
CREATE TABLE IF NOT EXISTS articles (
    id               BIGSERIAL PRIMARY KEY,
    source           TEXT        NOT NULL,                -- 'cafef'
    external_id      TEXT,                                -- id bài trên site (vd: 188261005230353967)
    url              TEXT        NOT NULL UNIQUE,
    canonical_url    TEXT,
    category         TEXT,                                -- 'Thị trường chứng khoán'
    title            TEXT        NOT NULL,
    sapo             TEXT,                                -- đoạn tóm tắt đầu bài
    author           TEXT,
    original_source  TEXT,                                -- nguồn gốc bài (vd: 'Nhịp sống thị trường')
    published_at     TIMESTAMPTZ,
    thumbnail_url    TEXT,
    tags             TEXT[]      NOT NULL DEFAULT '{}',
    content_text     TEXT,                                -- nội dung dạng text thuần
    content_markdown TEXT,                                -- nội dung dạng markdown (crawl4ai sinh ra)
    content_html     TEXT,                                -- HTML đã làm sạch của khung nội dung
    word_count       INTEGER,
    listing_url      TEXT,                                -- trang chuyên mục nơi phát hiện link
    listing_section  TEXT,                                -- 'featured' | 'stream'
    http_status      INTEGER,
    crawled_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_articles_source_published ON articles (source, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_tags ON articles USING GIN (tags);

-- Nhật ký mỗi lần chạy crawler
CREATE TABLE IF NOT EXISTS crawl_runs (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,
    listing_url   TEXT        NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT        NOT NULL DEFAULT 'running',  -- running | success | partial | failed
    links_found   INTEGER     NOT NULL DEFAULT 0,
    links_new     INTEGER     NOT NULL DEFAULT 0,
    saved         INTEGER     NOT NULL DEFAULT 0,
    failed        INTEGER     NOT NULL DEFAULT 0,
    errors        JSONB       NOT NULL DEFAULT '[]'::jsonb
);

-- Khoảng ngày đăng mà lần chạy nhắm tới (NULL = không lọc theo ngày) + số bài bỏ qua vì ngoài khoảng.
-- Dùng ALTER ... IF NOT EXISTS để DB cũ tự được nâng cấp khi crawler khởi động.
ALTER TABLE crawl_runs ADD COLUMN IF NOT EXISTS target_from DATE;
ALTER TABLE crawl_runs ADD COLUMN IF NOT EXISTS target_to   DATE;
ALTER TABLE crawl_runs ADD COLUMN IF NOT EXISTS skipped     INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at DESC);
