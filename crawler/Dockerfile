# Dùng lại image chính thức của Crawl4AI: đã có Python 3.12, crawl4ai 0.8.6,
# Playwright + Chromium cài sẵn cho user `appuser` -> không phải tự cài browser.
# Build context = thư mục gốc dự án (xem docker-compose.yaml).
FROM unclecode/crawl4ai:0.8.6

USER root
COPY crawler/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /opt/crawler
COPY crawler/app ./app
COPY config ./config
COPY init-db.sql ./init-db.sql

ENV PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS=ignore

# Chromium của Playwright nằm trong ~/.cache/ms-playwright của appuser
USER appuser

ENTRYPOINT ["python", "-m", "app"]
