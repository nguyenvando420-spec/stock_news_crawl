#!/usr/bin/env sh
set -eu
REGION=${1:-all}
if [ ! -f .env ]; then cp .env.example .env; fi
mkdir -p output
OUT="output/smoke_${REGION}.jsonl"
: > "$OUT"
docker compose up -d postgres crawl4ai
docker compose --profile run run --rm \
  -e ENABLE_POSTGRES=false -e OUTPUT_FILE="/data/smoke_${REGION}.jsonl" \
  crawler scrapy crawl news -a regions="$REGION" -a enrich=false -a max_items=1
printf '\nSmoke output: %s\n' "$OUT"
wc -l "$OUT" || true
