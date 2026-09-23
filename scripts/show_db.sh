#!/usr/bin/env sh
set -eu

if [ -f .env ]; then
  # export non-comment lines
  export $(grep -v '^#' .env | xargs) 2>/dev/null || true
fi

echo "=== Article Counts by Source ==="
docker compose exec -T postgres psql -U "${POSTGRES_USER:-crawler}" -d "${POSTGRES_DB:-crawler}" -c "
SELECT source, source_name, count(*) AS total_articles,
       count(content_markdown) AS enriched_articles
FROM articles
GROUP BY source, source_name
ORDER BY source;
"

echo "=== Latest 15 Articles in PostgreSQL ==="
docker compose exec -T postgres psql -U "${POSTGRES_USER:-crawler}" -d "${POSTGRES_DB:-crawler}" -c "
SELECT source, published_at, left(title, 60) AS title,
       length(coalesce(content_markdown, '')) AS md_bytes,
       renderer
FROM articles
ORDER BY crawled_at DESC
LIMIT 15;
"

