CREATE TABLE IF NOT EXISTS articles (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    source_name VARCHAR(255),
    region VARCHAR(32),
    language VARCHAR(16),
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    description TEXT,
    author TEXT,
    published_at TIMESTAMPTZ,
    content_markdown TEXT,
    content_html TEXT,
    discovery_method VARCHAR(32),
    renderer VARCHAR(32),
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_crawled_at ON articles(crawled_at DESC);
