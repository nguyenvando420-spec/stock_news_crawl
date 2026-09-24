#!/usr/bin/env python3
"""
View and explore crawled stock news articles.
Can be used via CLI or as a local web reader interface.

Usage:
    # CLI:
    python scripts/view_articles.py
    python scripts/view_articles.py --list -n 20
    python scripts/view_articles.py --region VN
    python scripts/view_articles.py --source cafef_stock
    python scripts/view_articles.py --search "chứng khoán"
    python scripts/view_articles.py --read 1

    # Web Dashboard / Reader:
    python scripts/view_articles.py --serve --port 8080
"""

import os
import sys
import json
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
from datetime import datetime

DEFAULT_JSONL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "articles.jsonl")

def load_articles(jsonl_path=DEFAULT_JSONL):
    if not os.path.exists(jsonl_path):
        return []
    
    articles_map = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                url = item.get("url")
                if url:
                    if url in articles_map:
                        existing = articles_map[url]
                        exist_blocked = (existing.get("title") == "Just a moment..." or "cf_chl" in (existing.get("content_markdown") or ""))
                        item_blocked = (item.get("title") == "Just a moment..." or "cf_chl" in (item.get("content_markdown") or ""))
                        if exist_blocked and not item_blocked:
                            articles_map[url] = item
                        elif not item_blocked and len(item.get("content_markdown") or "") >= len(existing.get("content_markdown") or ""):
                            articles_map[url] = item
                    else:
                        articles_map[url] = item
            except Exception:
                continue
                
    articles = list(articles_map.values())
    # Sort by published_at or crawled_at descending
    def get_sort_key(a):
        return a.get("published_at") or a.get("discovered_at") or ""
    articles.sort(key=get_sort_key, reverse=True)
    return articles

def print_article_list(articles, limit=20):
    total = len(articles)
    display_items = articles[:limit]
    print(f"\n📰 Hiển thị {len(display_items)} / {total} bài viết:")
    print("=" * 105)
    print(f"{'STT':<4} | {'Nguồn':<22} | {'Ngày đăng':<16} | {'Tiêu đề':<55}")
    print("-" * 105)
    
    for idx, a in enumerate(display_items, 1):
        source = (a.get("source_name") or a.get("source") or "Unknown")[:21]
        pub = (a.get("published_at") or "")[:16]
        title = (a.get("title") or "No title").strip().replace("\n", " ")
        if len(title) > 52:
            title = title[:50] + "..."
        print(f"{idx:<4} | {source:<22} | {pub:<16} | {title:<55}")
    print("=" * 105)
    print("💡 Mẹo: Dùng `python scripts/view_articles.py --read <STT>` để đọc toàn văn bài viết.")
    print("💡 Mẹo: Dùng `python scripts/view_articles.py --serve` để mở giao diện Web Reader trên trình duyệt!\n")

def read_article(articles, index):
    if index < 1 or index > len(articles):
        print(f"❌ Không tìm thấy bài viết số {index}. Tổng số bài hiện có: {len(articles)}")
        return
    a = articles[index - 1]
    print("\n" + "=" * 90)
    print(f"📌 TIÊU ĐỀ: {a.get('title')}")
    print("=" * 90)
    print(f"🏢 Nguồn:       {a.get('source_name')} ({a.get('source')})")
    print(f"🌍 Khu vực:     {a.get('region', '')} - {a.get('country', '')}")
    print(f"⏰ Ngày đăng:   {a.get('published_at', '')}")
    print(f"🔗 Link gốc:    {a.get('url', '')}")
    print(f"⚙️  Renderer:    {a.get('renderer', '')}")
    print("-" * 90)
    print("📝 NỘI DUNG:")
    print("-" * 90)
    content = a.get("content_markdown") or a.get("description") or "[Chưa có nội dung markdown đầy đủ]"
    print(content.strip())
    print("\n" + "=" * 90 + "\n")

# --- Embedded Web Server ---
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock News Reader - Tin Tức Chứng Khoán</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-body: #0d1117;
            --bg-sidebar: #161b22;
            --bg-card: #21262d;
            --bg-card-hover: #30363d;
            --border: #30363d;
            --text-main: #c9d1d9;
            --text-title: #f0f6fc;
            --text-muted: #8b949e;
            --accent: #58a6ff;
            --accent-green: #2ea043;
            --accent-tag: #1f6feb26;
            --accent-tag-text: #58a6ff;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--bg-body);
            color: var(--text-main);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }
        /* Sidebar */
        .sidebar {
            width: 320px;
            background: var(--bg-sidebar);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        .sidebar-header {
            padding: 18px 20px;
            border-bottom: 1px solid var(--border);
        }
        .brand {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-title);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .stats-badge {
            font-size: 0.75rem;
            background: var(--accent-tag);
            color: var(--accent-tag-text);
            padding: 4px 8px;
            border-radius: 12px;
            font-weight: 600;
            margin-top: 8px;
            display: inline-block;
        }
        .search-box {
            padding: 14px 20px;
            border-bottom: 1px solid var(--border);
        }
        .search-box input {
            width: 100%;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 9px 14px;
            color: var(--text-title);
            font-size: 0.88rem;
            outline: none;
            transition: border-color 0.2s;
        }
        .search-box input:focus {
            border-color: var(--accent);
        }
        .filter-section {
            padding: 12px 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .region-tabs {
            display: flex;
            background: var(--bg-card);
            border-radius: 6px;
            padding: 3px;
            gap: 4px;
        }
        .tab-btn {
            flex: 1;
            padding: 6px 10px;
            background: transparent;
            border: none;
            border-radius: 4px;
            color: var(--text-muted);
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tab-btn.active {
            background: var(--accent-tag-text);
            color: #fff;
        }
        select.source-select {
            width: 100%;
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 8px;
            border-radius: 6px;
            font-size: 0.85rem;
            outline: none;
        }
        .article-list {
            flex: 1;
            overflow-y: auto;
            padding: 10px;
        }
        .article-item {
            padding: 12px 14px;
            border-radius: 6px;
            cursor: pointer;
            border: 1px solid transparent;
            margin-bottom: 6px;
            transition: all 0.15s;
        }
        .article-item:hover {
            background: var(--bg-card);
            border-color: var(--border);
        }
        .article-item.active {
            background: var(--bg-card);
            border-color: var(--accent);
        }
        .article-item-title {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-title);
            line-height: 1.35;
            margin-bottom: 6px;
        }
        .article-meta {
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
            color: var(--text-muted);
        }
        .badge-source {
            font-weight: 500;
            color: var(--accent);
        }
        /* Content area */
        .content-area {
            flex: 1;
            overflow-y: auto;
            padding: 40px 60px;
            max-width: 960px;
            margin: 0 auto;
        }
        .empty-placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-muted);
            text-align: center;
            gap: 12px;
        }
        .article-detail-header {
            margin-bottom: 24px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
        }
        .article-detail-title {
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--text-title);
            line-height: 1.3;
            margin-bottom: 16px;
        }
        .article-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 14px;
        }
        .tag {
            background: var(--bg-card);
            border: 1px solid var(--border);
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.78rem;
            color: var(--text-main);
        }
        .tag.source-tag {
            background: var(--accent-tag);
            border-color: transparent;
            color: var(--accent-tag-text);
            font-weight: 600;
        }
        .article-links {
            margin-top: 10px;
        }
        .article-links a {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            color: var(--accent);
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .article-links a:hover {
            text-decoration: underline;
        }
        /* Markdown rendering */
        .article-body {
            line-height: 1.7;
            font-size: 1.05rem;
            color: var(--text-main);
        }
        .article-body h1, .article-body h2, .article-body h3 {
            color: var(--text-title);
            margin: 24px 0 12px;
        }
        .article-body p {
            margin-bottom: 16px;
        }
        .article-body img {
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            margin: 16px 0;
            border: 1px solid var(--border);
        }
        .article-body a {
            color: var(--accent);
        }
        .article-body blockquote {
            border-left: 4px solid var(--accent);
            padding-left: 16px;
            color: var(--text-muted);
            margin: 16px 0;
        }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <div class="brand">📈 Stock News Reader</div>
            <div class="stats-badge" id="stats">Đang tải dữ liệu...</div>
        </div>

        <div class="search-box">
            <input type="text" id="searchInput" placeholder="🔍 Tìm kiếm tiêu đề, từ khóa...">
        </div>

        <div class="filter-section">
            <div class="region-tabs">
                <button class="tab-btn active" data-region="ALL">Tất cả</button>
                <button class="tab-btn" data-region="VN">🇻🇳 Việt Nam</button>
                <button class="tab-btn" data-region="GLOBAL">🌐 Quốc tế</button>
            </div>
            <select class="source-select" id="sourceSelect">
                <option value="ALL">Tất cả nguồn tin</option>
            </select>
        </div>

        <div class="article-list" id="articleList"></div>
    </div>

    <div class="content-area" id="contentArea">
        <div class="empty-placeholder">
            <div style="font-size: 3rem;">📰</div>
            <h2>Chọn một bài viết ở danh sách bên trái</h2>
            <p>Dữ liệu được cập nhật từ Scrapy và Crawl4AI</p>
        </div>
    </div>

    <script>
        let allArticles = [];
        let filteredArticles = [];
        let currentRegion = 'ALL';
        let currentSource = 'ALL';
        let selectedIndex = -1;

        async function fetchArticles() {
            try {
                const res = await fetch('/api/articles');
                allArticles = await res.json();
                populateSources();
                filterArticles();
            } catch (err) {
                document.getElementById('stats').innerText = 'Lỗi tải dữ liệu';
            }
        }

        function populateSources() {
            const select = document.getElementById('sourceSelect');
            const sources = {};
            allArticles.forEach(a => {
                const key = a.source || 'other';
                const name = a.source_name || a.source || 'Khác';
                sources[key] = name;
            });
            Object.keys(sources).sort().forEach(key => {
                const opt = document.createElement('option');
                opt.value = key;
                opt.innerText = sources[key];
                select.appendChild(opt);
            });
        }

        function filterArticles() {
            const query = document.getElementById('searchInput').value.toLowerCase().trim();
            filteredArticles = allArticles.filter(a => {
                if (currentRegion !== 'ALL') {
                    const r = (a.region || '').toUpperCase();
                    if (currentRegion === 'VN' && r !== 'VN') return false;
                    if (currentRegion === 'GLOBAL' && r === 'VN') return false;
                }
                if (currentSource !== 'ALL' && a.source !== currentSource) {
                    return false;
                }
                if (query) {
                    const title = (a.title || '').toLowerCase();
                    const desc = (a.description || '').toLowerCase();
                    const content = (a.content_markdown || '').toLowerCase();
                    if (!title.includes(query) && !desc.includes(query) && !content.includes(query)) {
                        return false;
                    }
                }
                return true;
            });

            document.getElementById('stats').innerText = `${filteredArticles.length} / ${allArticles.length} bài viết`;
            renderList();
        }

        function renderList() {
            const listEl = document.getElementById('articleList');
            listEl.innerHTML = '';

            if (filteredArticles.length === 0) {
                listEl.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Không tìm thấy bài viết nào</div>';
                return;
            }

            filteredArticles.forEach((a, idx) => {
                const item = document.createElement('div');
                item.className = 'article-item' + (idx === selectedIndex ? ' active' : '');
                
                const pubDate = a.published_at ? a.published_at.substring(0, 10) : '';
                const sourceName = a.source_name || a.source;

                item.innerHTML = `
                    <div class="article-item-title">${escapeHtml(a.title || 'Không có tiêu đề')}</div>
                    <div class="article-meta">
                        <span class="badge-source">${escapeHtml(sourceName)}</span>
                        <span>${pubDate}</span>
                    </div>
                `;
                item.onclick = () => selectArticle(idx);
                listEl.appendChild(item);
            });
        }

        function selectArticle(idx) {
            selectedIndex = idx;
            document.querySelectorAll('.article-item').forEach((el, i) => {
                el.classList.toggle('active', i === idx);
            });

            const a = filteredArticles[idx];
            if (!a) return;

            const contentArea = document.getElementById('contentArea');
            const markdown = a.content_markdown || a.description || '_Không có nội dung chi tiết bài viết._';
            const parsedHtml = marked.parse(markdown);

            contentArea.innerHTML = `
                <div class="article-detail-header">
                    <div class="article-tags">
                        <span class="tag source-tag">${escapeHtml(a.source_name || a.source)}</span>
                        ${a.region ? `<span class="tag">${escapeHtml(a.region)}</span>` : ''}
                        ${a.category ? `<span class="tag">${escapeHtml(a.category)}</span>` : ''}
                        ${a.renderer ? `<span class="tag">Renderer: ${escapeHtml(a.renderer)}</span>` : ''}
                    </div>
                    <h1 class="article-detail-title">${escapeHtml(a.title || 'Không có tiêu đề')}</h1>
                    <div class="article-meta" style="margin-bottom: 12px; font-size: 0.85rem;">
                        <span>📅 Ngày xuất bản: <strong>${escapeHtml(a.published_at || 'Không rõ')}</strong></span>
                        ${a.author ? `<span>✍️ Tác giả: <strong>${escapeHtml(a.author)}</strong></span>` : ''}
                    </div>
                    <div class="article-links">
                        <a href="${escapeHtml(a.url)}" target="_blank" rel="noopener noreferrer">
                            ↗ Xem bài gốc tại website chính thức
                        </a>
                    </div>
                </div>
                <div class="article-body">
                    ${parsedHtml}
                </div>
            `;
            contentArea.scrollTop = 0;
        }

        function escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
        }

        // Event Listeners
        document.getElementById('searchInput').addEventListener('input', () => {
            selectedIndex = -1;
            filterArticles();
        });

        document.getElementById('sourceSelect').addEventListener('change', (e) => {
            currentSource = e.target.value;
            selectedIndex = -1;
            filterArticles();
        });

        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                currentRegion = e.target.getAttribute('data-region');
                selectedIndex = -1;
                filterArticles();
            });
        });

        fetchArticles();
    </script>
</body>
</html>
"""

class SimpleServer(BaseHTTPRequestHandler):
    articles = []

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif parsed.path == "/api/articles":
            jsonl_file = getattr(self.server, "file_path", DEFAULT_JSONL)
            try:
                articles = load_articles(jsonl_file)
            except Exception:
                articles = self.articles
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(articles, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence verbose logs
        return

def serve_web(articles, port=8080, file_path=DEFAULT_JSONL):
    SimpleServer.articles = articles
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleServer)
    httpd.file_path = file_path
    print(f"\n🚀 Đang chạy Web Reader tại: http://localhost:{port}")
    print(f"📊 Đã tải {len(articles)} bài viết từ {file_path}")
    print("Nhấn Ctrl + C để dừng máy chủ.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Đã dừng Web Reader.")

def main():
    parser = argparse.ArgumentParser(description="Xem và khám phá tin tức chứng khoán đã crawl.")
    parser.add_argument("--list", action="store_true", help="Hiển thị danh sách bài viết dạng bảng")
    parser.add_argument("-n", "--limit", type=int, default=20, help="Số lượng bài viết hiển thị (mặc định: 20)")
    parser.add_argument("--source", type=str, help="Lọc bài viết theo source key (vd: cafef_stock)")
    parser.add_argument("--region", type=str, choices=["VN", "GLOBAL", "all"], help="Lọc bài viết theo khu vực")
    parser.add_argument("--search", type=str, help="Tìm kiếm theo từ khóa trong tiêu đề/nội dung")
    parser.add_argument("--read", type=int, help="Đọc toàn văn bài viết theo số thứ tự (STT)")
    parser.add_argument("--serve", action="store_true", help="Khởi chạy giao diện Web Reader trên trình duyệt")
    parser.add_argument("--port", type=int, default=8080, help="Cổng chạy Web Reader (mặc định: 8080)")
    parser.add_argument("--file", type=str, default=DEFAULT_JSONL, help="Đường dẫn tới file articles.jsonl")

    args = parser.parse_args()
    articles = load_articles(args.file)

    if not articles:
        print(f"⚠️ Chưa tìm thấy bài viết nào trong {args.file}!")
        return

    # Filter by region
    if args.region and args.region.upper() != "ALL":
        r = args.region.upper()
        if r == "VN":
            articles = [a for a in articles if (a.get("region") or "").upper() == "VN"]
        elif r == "GLOBAL":
            articles = [a for a in articles if (a.get("region") or "").upper() != "VN"]

    # Filter by source
    if args.source:
        s = args.source.lower()
        articles = [a for a in articles if (a.get("source") or "").lower() == s]

    # Search keyword
    if args.search:
        q = args.search.lower()
        articles = [a for a in articles if q in (a.get("title") or "").lower() 
                    or q in (a.get("description") or "").lower() 
                    or q in (a.get("content_markdown") or "").lower()]

    if args.serve:
        serve_web(articles, port=args.port, file_path=args.file)
    elif args.read is not None:
        read_article(articles, args.read)
    else:
        print_article_list(articles, limit=args.limit)

if __name__ == "__main__":
    main()
