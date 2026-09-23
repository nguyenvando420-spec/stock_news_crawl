#!/usr/bin/env sh
set -eu

# Ensure .env exists with a secure random token
if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example..."
  cp .env.example .env
  TOKEN=$(openssl rand -hex 32 2>/dev/null || date +%s | sha256sum | head -c 64)
  if [ "$(uname)" = "Darwin" ]; then
    sed -i '' "s/change-me-to-a-long-random-token/$TOKEN/" .env
  else
    sed -i "s/change-me-to-a-long-random-token/$TOKEN/" .env
  fi
fi

mkdir -p output
: > output/articles.jsonl

docker compose up -d postgres crawl4ai
docker compose --profile run run --rm crawler scrapy crawl news -a enrich=false

COUNT=$(wc -l < output/articles.jsonl | tr -d ' ')
printf '\n=== RSS Crawl Completed: %s articles discovered ===\n' "$COUNT"
tail -n 10 output/articles.jsonl || true

