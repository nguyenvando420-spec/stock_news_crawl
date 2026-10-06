#!/usr/bin/env bash
# Xem nhanh dữ liệu đã crawl trong PostgreSQL
#   ./scripts/show_db.sh            -> tổng quan, 20 bài mới nhất, số bài theo ngày đăng (7 ngày), 8 lần chạy gần nhất
#   ./scripts/show_db.sh <id>       -> chi tiết 1 bài (metadata + 1500 ký tự nội dung đầu)
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL=(docker compose exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-news_db}" -P pager=off)

if [[ $# -ge 1 ]]; then
  "${PSQL[@]}" -x -c "
    SELECT id, source, external_id, url, category, title, sapo, author, original_source,
           published_at, tags, word_count, listing_section, crawled_at,
           left(content_text, 1500) AS content_preview
    FROM articles WHERE id = $1;"
  exit 0
fi

"${PSQL[@]}" -c "
  SELECT count(*) AS total_articles,
         count(*) FILTER (WHERE crawled_at > now() - interval '1 day') AS last_24h,
         min(published_at) AS oldest, max(published_at) AS newest
  FROM articles;"

"${PSQL[@]}" -c "
  SELECT id, to_char(published_at, 'DD/MM HH24:MI') AS published, listing_section AS section,
         word_count AS words, left(title, 80) AS title
  FROM articles ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 20;"

"${PSQL[@]}" -c "
  SELECT to_char(published_at AT TIME ZONE 'Asia/Ho_Chi_Minh', 'YYYY-MM-DD') AS ngay_dang, source, count(*) AS bai
  FROM articles WHERE published_at > now() - interval '7 days'
  GROUP BY 1, 2 ORDER BY 1 DESC, 2;"

"${PSQL[@]}" -c "
  SELECT id, source, to_char(started_at, 'DD/MM HH24:MI:SS') AS started, status,
         coalesce(target_from::text || CASE WHEN target_to <> target_from THEN ' → ' || target_to ELSE '' END, '-') AS target,
         links_found AS found, links_new AS new, saved, skipped, failed,
         round(extract(epoch FROM finished_at - started_at)) AS secs
  FROM crawl_runs ORDER BY id DESC LIMIT 8;"
