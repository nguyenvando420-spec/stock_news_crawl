import re
import psycopg2
from datetime import datetime

# Connect to postgres
conn = psycopg2.connect(
    dbname="automation_data",
    user="postgres",
    password="automation_secure_password_2026",
    host="localhost",
    port=5433
)
cur = conn.cursor()

cur.execute("SELECT id, url, title, summary, content_raw, source_name, source_category, published_date, author FROM public.crawled_articles;")
rows = cur.fetchall()

updated_count = 0

for row in rows:
    art_id, url, title, summary, content_raw, source_name, source_category, pub_date, author = row
    content_raw = content_raw or ""
    
    # 1. Author extraction
    new_author = author
    if not new_author:
        author_match = re.search(r'(?:^|\n)\s*(?:Bài và ảnh|Ảnh|Theo|Nguồn|Nguồn tin|Tác giả|Phóng viên|Ký giả|PV)[\s:]+([A-ZÀ-Ỹa-zà-ỹ0-9\s\.\-]{3,60})(?:\n|$)', content_raw, re.IGNORECASE)
        if author_match:
            new_author = author_match.group(1).strip()
        else:
            bold_match = re.search(r'(?:^|\n)\s*\*{1,2}([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})\*{1,2}\s*(?:\([^\)]+\))?\s*$', content_raw, re.MULTILINE)
            if bold_match:
                new_author = bold_match.group(1).strip()
    if not new_author:
        new_author = source_name or 'Ban Biên Tập'

    # 2. Published date extraction
    new_pub_date = pub_date
    if not new_pub_date and content_raw:
        d_match = re.search(r'(?:cập nhật ngày|ngày đăng|đăng ngày|thời gian|ngày|xuất bản)[\s:]*([0-3]?[0-9][\/\-\.][0-1]?[0-9][\/\-\.][1-2][0-9]{3}(?:\s*[\-,]?\s*[0-2]?[0-9]:[0-5][0-9](?::[0-5][0-9])?)?)', content_raw, re.IGNORECASE)
        if d_match:
            date_str = d_match.group(1).strip()
            parts = re.search(r'([0-3]?[0-9])[\/\-\.]([0-1]?[0-9])[\/\-\.]([1-2][0-9]{3})(?:\s*[\-,]?\s*([0-2]?[0-9]):([0-5][0-9])(?::([0-5][0-9]))?)?', date_str)
            if parts:
                day = parts.group(1).zfill(2)
                month = parts.group(2).zfill(2)
                year = parts.group(3)
                hour = (parts.group(4) or '07').zfill(2)
                minute = (parts.group(5) or '00').zfill(2)
                second = (parts.group(6) or '00').zfill(2)
                iso_cand = f"{year}-{month}-{day}T{hour}:{minute}:{second}+07:00"
                try:
                    new_pub_date = datetime.fromisoformat(iso_cand)
                except Exception:
                    pass
    if not new_pub_date and url:
        url_match = re.search(r'/(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})', url)
        if url_match:
            iso_cand = f"{url_match.group(1)}-{url_match.group(2).zfill(2)}-{url_match.group(3).zfill(2)}T07:00:00+07:00"
            try:
                new_pub_date = datetime.fromisoformat(iso_cand)
            except Exception:
                pass

    # 3. Summary check
    new_summary = summary
    if not new_summary or len(new_summary) < 20:
        clean_md = re.sub(r'^#+.*$', '', content_raw, flags=re.MULTILINE)
        clean_md = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean_md)
        clean_md = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean_md)
        clean_md = re.sub(r'[*_`]', '', clean_md).strip()
        paras = [p.strip() for p in clean_md.split('\n\n') if len(p.strip()) > 40 and not p.strip().startswith('Tin ') and not p.strip().startswith('Cập nhật')]
        if paras:
            new_summary = paras[0][:350].strip()
            if len(paras[0]) > 350:
                new_summary += '...'
    if not new_summary:
        new_summary = f"Nội dung cập nhật từ {source_name}"

    cur.execute("""
        UPDATE public.crawled_articles 
        SET author = %s, published_date = %s, summary = %s, updated_at = NOW() 
        WHERE id = %s
    """, (new_author, new_pub_date, new_summary, art_id))
    updated_count += 1

conn.commit()
cur.close()
conn.close()

print(f"Successfully backfilled metadata for {updated_count} articles!")
