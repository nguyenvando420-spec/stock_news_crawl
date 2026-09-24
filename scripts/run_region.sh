#!/usr/bin/env sh
set -eu
REGION=${1:-VN}
ENRICH=${2:-auto}
MAX_ITEMS=${3:-5}

if [ ! -f .env ]; then
  cp .env.example .env
  TOKEN=$(openssl rand -hex 32 2>/dev/null || date +%s | sha256sum | head -c 64)
  if [ "$(uname)" = "Darwin" ]; then
    sed -i '' "s/change-me-to-a-long-random-token/$TOKEN/" .env
  else
    sed -i "s/change-me-to-a-long-random-token/$TOKEN/" .env
  fi
fi
mkdir -p output
docker compose up -d postgres crawl4ai
exec docker compose --profile run run --rm crawler \
  scrapy crawl news -a regions="$REGION" -a enrich="$ENRICH" -a max_items="$MAX_ITEMS"
