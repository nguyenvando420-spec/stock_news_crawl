import json

with open('n8n_news_aggregator_workflow.json', 'r', encoding='utf-8') as f:
    wf = json.load(f)

nodes = wf.get('nodes', [])
connections = wf.get('connections', {})

# 1. Tăng số bài mỗi nguồn trong Node 4 từ 6 lên 10
for n in nodes:
    if n.get('name') == '4. Lọc URL Bài Viết (Code)':
        js = n['parameters']['jsCode']
        js = js.replace('candidateLinks.slice(0, 6);', 'candidateLinks.slice(0, 10);')
        n['parameters']['jsCode'] = js
        print('Updated Node 4: slice(0, 10)')

# 2. Xóa Node 10 khỏi danh sách nodes
nodes = [n for n in nodes if n.get('name') != '10. Duyệt từng Bài Viết Mới']
print('Removed Node 10 from nodes list')

# 3. Cập nhật Node 13 để xử lý mảng $input.all() thay vì $input.first()
node13_code = """// Node 13: Chuẩn hóa & Trích xuất Chi tiết Bài Báo (Hỗ trợ xử lý toàn bộ mảng bài viết)
const inputItems = $input.all();
let sourceInfo = {};
try {
  sourceInfo = $('4. Lọc URL Bài Viết (Code)').last().json || {};
} catch(e) {
  sourceInfo = {};
}

let newUrlItems = [];
try {
  newUrlItems = $('9. Tách từng Bài Viết Mới (Code)').all() || [];
} catch(e) {
  newUrlItems = [];
}

const results = [];

function createHash(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(16);
}

function parseToIso(dateVal) {
  if (!dateVal) return null;
  if (typeof dateVal === 'number' || (typeof dateVal === 'string' && /^\\d{10,13}$/.test(String(dateVal).trim()))) {
    const num = parseInt(String(dateVal).trim(), 10);
    const d = new Date(num < 1e11 ? num * 1000 : num);
    if (!isNaN(d.getTime())) return d.toISOString();
  }
  const d = new Date(dateVal);
  if (!isNaN(d.getTime())) return d.toISOString();
  return null;
}

for (let i = 0; i < inputItems.length; i++) {
  const firecrawlRes = inputItems[i].json || {};
  const currentArticle = newUrlItems[i]?.json || {};
  
  const metadata = firecrawlRes.data?.metadata || firecrawlRes.metadata || {};
  const markdown = firecrawlRes.data?.markdown || firecrawlRes.markdown || firecrawlRes.data?.content || '';
  
  const articleUrl = currentArticle.article_url || metadata.sourceURL || metadata.url || '';
  if (!articleUrl) continue;

  // 1. Tiêu đề bài viết
  let title = '';
  if (markdown) {
    const headingMatch = markdown.match(/^#{1,3}\\s+(.+)$/m);
    if (headingMatch && headingMatch[1].trim().length > 5) {
      const cand = headingMatch[1].replace(/\\[([^\\]]+)\\]\\([^)]+\\)/g, '$1').replace(/[*_`]/g, '').trim();
      const lower = cand.toLowerCase();
      const blacklist = ['tin tức', 'thống kê', 'tin cùng tổ chức', 'tin khác', 'menu', 'trang chủ', 'bình luận', 'ý kiến', 'thông báo', 'văn bản mới'];
      if (!blacklist.includes(lower)) {
        title = cand;
      }
    }
  }
  if (!title) {
    title = metadata.ogTitle || metadata['og:title'] || metadata.title || metadata.its_title || metadata.headline || '';
  }
  title = title.replace(/\\s*[-|–—]\\s*(?:Báo\\s+|Trang tin\\s+|Cổng TT\\s+)?[A-ZÀ-Ỹa-zà-ỹ0-9\\s\\.]+(?:\\.vn|\\.com|\\.net)?$/i, '').trim();
  if (!title) {
    title = 'Bài viết từ ' + (currentArticle.source_name || sourceInfo.source_name || 'Nguồn tin');
  }

  // 2. Ngày xuất bản
  let publishedDate = null;
  const rawDateCand = metadata['article:published_time'] || 
                      metadata.pubdate || 
                      metadata.publishedTime || 
                      metadata['datePublished'] || 
                      metadata.date || 
                      metadata['dc.date'] || 
                      metadata.lastmod || 
                      metadata['article:modified_time'] ||
                      metadata.its_publication || null;

  publishedDate = parseToIso(rawDateCand);

  if (!publishedDate && markdown) {
    const dMatch = markdown.match(/(?:cập nhật ngày|ngày đăng|đăng ngày|thời gian|ngày|xuất bản)[\\s:]*([0-3]?[0-9][\\/\\-\\.][0-1]?[0-9][\\/\\-\\.][1-2][0-9]{3}(?:\\s*[\\-,]?\\s*[0-2]?[0-9]:[0-5][0-9](?::[0-5][0-9])?)?)/i);
    if (dMatch) {
      const dateStr = dMatch[1].trim();
      const parts = dateStr.match(/([0-3]?[0-9])[\\/\\-\\.]([0-1]?[0-9])[\\/\\-\\.]([1-2][0-9]{3})(?:\\s*[\\-,]?\\s*([0-2]?[0-9]):([0-5][0-9])(?::([0-5][0-9]))?)?/);
      if (parts) {
        const day = parts[1].padStart(2, '0');
        const month = parts[2].padStart(2, '0');
        const year = parts[3];
        const hour = (parts[4] || '07').padStart(2, '0');
        const minute = (parts[5] || '00').padStart(2, '0');
        const second = (parts[6] || '00').padStart(2, '0');
        const isoCand = `${year}-${month}-${day}T${hour}:${minute}:${second}+07:00`;
        const d = new Date(isoCand);
        if (!isNaN(d.getTime())) publishedDate = d.toISOString();
      }
    }
  }

  if (!publishedDate && articleUrl) {
    const urlDateMatch = articleUrl.match(/\\/(\\d{4})[\\/\\-](\\d{1,2})[\\/\\-](\\d{1,2})/);
    if (urlDateMatch) {
      const isoCand = `${urlDateMatch[1]}-${urlDateMatch[2].padStart(2, '0')}-${urlDateMatch[3].padStart(2, '0')}T07:00:00+07:00`;
      const d = new Date(isoCand);
      if (!isNaN(d.getTime())) publishedDate = d.toISOString();
    }
  }

  // 3. Tác giả
  let author = metadata.author || 
               metadata['article:author'] || 
               metadata['dc.creator'] || 
               metadata['og:author'] || 
               metadata.creator || 
               metadata['twitter:creator'] || '';

  if (typeof author === 'string') {
    author = author.replace(/^@/, '').trim();
  } else if (Array.isArray(author)) {
    author = author.map(a => (typeof a === 'object' ? a.name || '' : String(a))).filter(Boolean).join(', ');
  } else if (typeof author === 'object' && author !== null) {
    author = author.name || '';
  } else {
    author = '';
  }

  if (!author && markdown) {
    const authorMatch = markdown.match(/(?:^|\\n)\\s*(?:Bài và ảnh|Ảnh|Theo|Nguồn|Nguồn tin|Tác giả|Phóng viên|Ký giả|PV)[\\s:]+([A-ZÀ-Ỹa-zà-ỹ0-9\\s\\.\\-]{3,60})(?:\\n|$)/i);
    if (authorMatch) {
      author = authorMatch[1].trim();
    } else {
      const boldAuthorMatch = markdown.match(/(?:^|\\n)\\s*\\*{1,2}([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})\\*{1,2}\\s*(?:\\([^\\)]+\\))?\\s*$/m);
      if (boldAuthorMatch) {
        author = boldAuthorMatch[1].trim();
      }
    }
  }
  if (!author) {
    author = currentArticle.source_name || sourceInfo.source_name || metadata.ogSiteName || metadata.source || 'Ban Biên Tập';
  }

  // 4. Tóm tắt
  let summary = metadata.description || metadata.ogDescription || metadata['og:description'] || metadata['twitter:description'] || '';
  if (summary) {
    summary = summary.replace(/^[-—|\\s]+/, '').trim();
  }
  if (!summary || summary.length < 30) {
    if (markdown) {
      const cleanMd = markdown
        .replace(/^#+.*$/gm, '')
        .replace(/!\\[[^\\]]*\\]\\([^)]+\\)/g, '')
        .replace(/\\[([^\\]]+)\\]\\([^)]+\\)/g, '$1')
        .replace(/[*_`]/g, '')
        .trim();
      const paragraphs = cleanMd.split(/\\n\\s*\\n/).map(p => p.trim()).filter(p => p.length > 40 && !p.startsWith('Tin ') && !p.startsWith('Cập nhật') && !p.startsWith('Ảnh:'));
      if (paragraphs.length > 0) {
        summary = paragraphs[0].slice(0, 350).trim();
        if (paragraphs[0].length > 350) summary += '...';
      }
    }
  }
  if (!summary) {
    summary = 'Nội dung cập nhật từ ' + (currentArticle.source_name || sourceInfo.source_name || 'nguồn tin');
  }

  // 5. Tags, Điểm chính & Cảm xúc
  const rawTags = metadata.keywords || metadata['article:tag'] || '';
  let tags = [];
  if (Array.isArray(rawTags)) {
    tags = rawTags.map(t => String(t).trim()).filter(Boolean);
  } else if (typeof rawTags === 'string' && rawTags.length > 0) {
    tags = rawTags.split(',').map(t => t.trim()).filter(t => t.length > 1 && t.length < 50);
  }
  const cat = currentArticle.source_category || sourceInfo.source_category || 'Tin tức';
  if (cat && !tags.includes(cat)) {
    tags.unshift(cat);
  }
  tags = tags.slice(0, 6);

  const keyPoints = [];
  if (markdown) {
    const bulletMatches = markdown.match(/^[*-]\\s+([^\\n]+)$/gm);
    if (bulletMatches && bulletMatches.length > 0) {
      for (const b of bulletMatches.slice(0, 3)) {
        const cleanB = b.replace(/^[*-]\\s+/, '').replace(/\\[([^\\]]+)\\]\\([^)]+\\)/g, '$1').replace(/[*_`]/g, '').trim();
        if (cleanB.length > 15 && cleanB.length < 250) keyPoints.push(cleanB);
      }
    }
  }
  if (keyPoints.length === 0 && summary) {
    keyPoints.push(summary.slice(0, 200));
  }

  let sentiment = 'Trung lập';
  const fullTextLower = (title + ' ' + summary).toLowerCase();
  const positiveKeywords = ['tăng trưởng', 'tăng mạnh', 'khởi sắc', 'kỷ lục', 'lợi nhuận', 'mua ròng', 'bứt phá', 'lạc quan', 'thành công', 'phục hồi'];
  const negativeKeywords = ['giảm sâu', 'lao dốc', 'thua lỗ', 'khó khăn', 'xử phạt', 'sai phạm', 'khởi tố', 'bắt giữ', 'vỡ nợ', 'suy thoái', 'áp lực'];
  const posScore = positiveKeywords.filter(k => fullTextLower.includes(k)).length;
  const negScore = negativeKeywords.filter(k => fullTextLower.includes(k)).length;
  if (posScore > negScore && posScore >= 1) {
    sentiment = 'Tích cực';
  } else if (negScore > posScore && negScore >= 1) {
    sentiment = 'Tiêu cực';
  }

  const structuredData = {
    author,
    published_date: publishedDate,
    source_name: currentArticle.source_name || sourceInfo.source_name || '',
    source_category: cat,
    language: metadata.language || metadata.Language || 'vi',
    og_image: metadata.ogImage || metadata['og:image'] || metadata.twitterImage || null,
    canonical_url: metadata.canonicalURL || metadata.ogUrl || metadata.url || articleUrl,
    keywords: tags,
    firecrawl_scrape_id: metadata.scrapeId || null
  };

  const cleanTitle = (title || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\\u0300-\\u036f]/g, '')
    .replace(/[^a-z0-9\\s]/g, '')
    .replace(/\\s+/g, ' ')
    .trim();

  const titleHash = createHash(cleanTitle);

  results.push({
    json: {
      title: title.trim(),
      url: articleUrl,
      summary: summary.trim(),
      content_raw: markdown.slice(0, 30000),
      author: author.trim(),
      key_points: keyPoints,
      source_name: currentArticle.source_name || sourceInfo.source_name || '',
      source_category: cat,
      source_url: currentArticle.source_url || sourceInfo.source_url || '',
      sentiment: sentiment,
      tags: tags,
      title_hash: titleHash,
      structured_data: structuredData,
      published_date: publishedDate
    }
  });
}

return results;
"""

for n in nodes:
    if n.get('name') == '13. Chuẩn hóa & Trích xuất Chi tiết (Code)':
        n['parameters']['jsCode'] = node13_code
        print('Updated Node 13 jsCode to process full array')

# 4. Thêm Node 14b để gom tín hiệu kết thúc nguồn về đúng 1 item duy nhất
node14b = {
    "parameters": {
        "jsCode": """// Node 14b: Báo hoàn tất cào toàn bộ bài viết của nguồn này (chỉ trả về 1 item để trigger tiếp nguồn sau)
return [{
  json: {
    status: 'articles_batch_completed',
    processed_count: $input.all().length
  }
}];"""
    },
    "id": "source-articles-completed",
    "name": "14b. Hoàn tất Cào Nguồn (Code)",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [3400, 160]
}
nodes.append(node14b)
print('Added Node 14b')

# Điều chỉnh lại position của Node 15 cho đẹp mắt
for n in nodes:
    if n.get('name') == '15. Cập nhật Lịch Cào Nguồn (Postgres)':
        n['position'] = [3620, 240]

# 5. Cấu trúc lại toàn bộ connections
new_connections = {
    "Khi bấm Test (Manual Trigger)": connections.get("Khi bấm Test (Manual Trigger)", {}),
    "Lập lịch định kỳ (Mỗi 30 phút)": connections.get("Lập lịch định kỳ (Mỗi 30 phút)", {}),
    "1. Lấy Danh Sách Trang Danh Mục (Postgres)": {
        "main": [
            [
                {
                    "node": "2. Duyệt từng Nguồn Danh Mục",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "2. Duyệt từng Nguồn Danh Mục": {
        "main": [
            [],
            [
                {
                    "node": "3. Cào Links từ Trang Danh Mục (Firecrawl)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "3. Cào Links từ Trang Danh Mục (Firecrawl)": {
        "main": [
            [
                {
                    "node": "4. Lọc URL Bài Viết (Code)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "4. Lọc URL Bài Viết (Code)": {
        "main": [
            [
                {
                    "node": "5. Có Link Bài Viết Không?",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "5. Có Link Bài Viết Không?": {
        "main": [
            [
                {
                    "node": "6. Kiểm tra URL đã có trong DB (Postgres)",
                    "type": "main",
                    "index": 0
                }
            ],
            [
                {
                    "node": "15. Cập nhật Lịch Cào Nguồn (Postgres)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "6. Kiểm tra URL đã có trong DB (Postgres)": {
        "main": [
            [
                {
                    "node": "7. Lọc Link Mới Chưa Cào (Code)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "7. Lọc Link Mới Chưa Cào (Code)": {
        "main": [
            [
                {
                    "node": "8. Có bài mới cần cào không?",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "8. Có bài mới cần cào không?": {
        "main": [
            [
                {
                    "node": "9. Tách từng Bài Viết Mới (Code)",
                    "type": "main",
                    "index": 0
                }
            ],
            [
                {
                    "node": "15. Cập nhật Lịch Cào Nguồn (Postgres)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "9. Tách từng Bài Viết Mới (Code)": {
        "main": [
            [
                {
                    "node": "11. Cào Toàn Văn Bài Báo (Firecrawl)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "11. Cào Toàn Văn Bài Báo (Firecrawl)": {
        "main": [
            [
                {
                    "node": "13. Chuẩn hóa & Trích xuất Chi tiết (Code)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "13. Chuẩn hóa & Trích xuất Chi tiết (Code)": {
        "main": [
            [
                {
                    "node": "14. Lưu Bài Viết & Chống Trùng (Postgres)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "14. Lưu Bài Viết & Chống Trùng (Postgres)": {
        "main": [
            [
                {
                    "node": "14b. Hoàn tất Cào Nguồn (Code)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "14b. Hoàn tất Cào Nguồn (Code)": {
        "main": [
            [
                {
                    "node": "15. Cập nhật Lịch Cào Nguồn (Postgres)",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "15. Cập nhật Lịch Cào Nguồn (Postgres)": {
        "main": [
            [
                {
                    "node": "2. Duyệt từng Nguồn Danh Mục",
                    "type": "main",
                    "index": 0
                }
            ]
        ]
    },
    "Bấm để Thêm Nguồn (Manual Trigger)": connections.get("Bấm để Thêm Nguồn (Manual Trigger)", {}),
    "Khai báo Nguồn Cần Thêm (Code)": connections.get("Khai báo Nguồn Cần Thêm (Code)", {}),
    "Webhook Thêm Nguồn (POST)": connections.get("Webhook Thêm Nguồn (POST)", {})
}

wf['nodes'] = nodes
wf['connections'] = new_connections

with open('n8n_news_aggregator_workflow.json', 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print('Successfully restructured workflow and removed Node 10!')
