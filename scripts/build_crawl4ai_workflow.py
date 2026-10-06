import json

def build_workflow():
    workflow = {
        "name": "Crawl4AI & n8n News Pipeline (2-Stage Auto Crawler)",
        "id": "crawl4aiNewsAggr2026",
        "nodes": [
            {
                "parameters": {},
                "id": "trigger-manual",
                "name": "Khi bấm Test (Manual Trigger)",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [100, 260]
            },
            {
                "parameters": {
                    "rule": {
                        "interval": [
                            {
                                "field": "minutes",
                                "minutesInterval": 30
                            }
                        ]
                    }
                },
                "id": "trigger-schedule",
                "name": "Lập lịch định kỳ (Mỗi 30 phút)",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [100, 440]
            },
            {
                "parameters": {
                    "operation": "executeQuery",
                    "query": "SELECT id, source_name, source_category, source_url FROM public.crawl_targets WHERE active = true ORDER BY id ASC;"
                },
                "id": "get-sources",
                "name": "1. Lấy Danh Sách Trang Danh Mục (Postgres)",
                "type": "n8n-nodes-base.postgres",
                "typeVersion": 2.5,
                "position": [320, 340],
                "credentials": {
                    "postgres": {
                        "id": "sHxc5RWg5GkqDMcY",
                        "name": "Postgres account"
                    }
                }
            },
            {
                "parameters": {
                    "batchSize": 1,
                    "options": {}
                },
                "id": "loop-sources",
                "name": "2. Duyệt từng Nguồn Danh Mục",
                "type": "n8n-nodes-base.splitInBatches",
                "typeVersion": 3,
                "position": [540, 340]
            },
            {
                "parameters": {
                    "method": "POST",
                    "url": "http://crawl4ai:11235/crawl",
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [
                            {
                                "name": "Authorization",
                                "value": "Bearer crawl4ai_secret_token_2026"
                            },
                            {
                                "name": "Content-Type",
                                "value": "application/json"
                            }
                        ]
                    },
                    "sendBody": True,
                    "specifyBody": "json",
                    "jsonBody": "={{\n  JSON.stringify({\n    urls: [ $json.source_url || $('2. Duyệt từng Nguồn Danh Mục').item.json.source_url ],\n    priority: 10,\n    crawler_params: {\n      headless: true,\n      magic: true,\n      simulate_user: true\n    }\n  })\n}}",
                    "options": {
                        "timeout": 60000,
                        "response": {
                            "response": {
                                "responseFormat": "json"
                            }
                        }
                    }
                },
                "id": "crawl-links-crawl4ai",
                "name": "3. Cào Links Danh Mục (Crawl4AI)",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [760, 340],
                "onError": "continueRegularOutput"
            },
            {
                "parameters": {
                    "jsCode": """// Node 4: Lọc URL Bài Viết (Code) - Hỗ trợ Crawl4AI cho mọi nguồn tin
function parseUrlString(urlStr, baseOrigin) {
  if (!urlStr || typeof urlStr !== 'string') return null;
  let full = urlStr.trim().split('#')[0];
  if (full.startsWith('//')) {
    full = 'https:' + full;
  } else if (full.startsWith('/')) {
    full = (baseOrigin || '').replace(/\\/+$/, '') + full;
  } else if (!full.startsWith('http://') && !full.startsWith('https://')) {
    return null;
  }
  const match = full.match(/^https?:\\/\\/([^\\/?#]+)([^?#]*)(\\?[^#]*)?/i);
  if (!match) return null;
  return {
    full,
    host: (match[1] || '').toLowerCase(),
    pathname: match[2] || '/',
    search: match[3] || ''
  };
}

// 1. Trích xuất links từ đầu vào Crawl4AI
const allInputItems = $input.all();
let rawLinks = [];

for (const item of allInputItems) {
  let j = item.json || {};
  if (typeof j === 'string') {
    try { j = JSON.parse(j); } catch(e) {}
  }
  if (typeof j.data === 'string') {
    try { j = JSON.parse(j.data); } catch(e) {}
  }
  
  const crawlResult = (Array.isArray(j.results) ? j.results[0] : (j.result || j.data || j)) || {};
  const linksObj = crawlResult.links || {};

  // Lấy links nội bộ trích xuất bởi Crawl4AI
  if (Array.isArray(linksObj.internal)) {
    for (const l of linksObj.internal) {
      if (typeof l === 'string') rawLinks.push(l);
      else if (l && l.href) rawLinks.push(l.href);
    }
  }
  if (Array.isArray(linksObj)) {
    for (const l of linksObj) {
      if (typeof l === 'string') rawLinks.push(l);
      else if (l && l.href) rawLinks.push(l.href);
    }
  }

  // Fallback: quét link markdown nếu có
  const md = typeof crawlResult.markdown === 'string' ? crawlResult.markdown : (crawlResult.markdown?.raw_markdown || '');
  if (md) {
    const mdLinkMatches = md.match(/\\]\\((https?:\\/\\/[^\\)\\s]+)\\)/g);
    if (mdLinkMatches) {
      for (const m of mdLinkMatches) {
        const u = m.replace(/^\\]\\(/, '').replace(/\\)$/, '');
        rawLinks.push(u);
      }
    }
  }
}

// 2. Xác định thông tin nguồn tin hiện tại từ Node 2
let currentSource = null;
try {
  const node2Item = $('2. Duyệt từng Nguồn Danh Mục').item.json;
  if (node2Item && node2Item.source_url) {
    currentSource = {
      id: node2Item.id,
      name: node2Item.source_name,
      cat: node2Item.source_category,
      url: node2Item.source_url
    };
  }
} catch (e) {}

if (!currentSource) {
  try {
    const node2Last = $('2. Duyệt từng Nguồn Danh Mục').last().json;
    if (node2Last && node2Last.source_url) {
      currentSource = {
        id: node2Last.id,
        name: node2Last.source_name,
        cat: node2Last.source_category,
        url: node2Last.source_url
      };
    }
  } catch (e) {}
}

if (!currentSource) {
  currentSource = {
    id: 0,
    name: 'Nguồn tin',
    cat: 'Tin tức',
    url: ''
  };
}

let currentOrigin = '';
const originMatch = (currentSource.url || '').match(/^(https?:\\/\\/[^\\/?#]+)/i);
if (originMatch) {
  currentOrigin = originMatch[1];
}

// 3. Bộ lọc rác và tài nguyên tĩnh
const assetRegex = /\\.(png|jpe?g|gif|webp|svg|css|js|ico|pdf|zip|mp4|mp3|docx?|xlsx?)(\\?.*)?$/i;
const excludePatterns = [
  '/tag/', '/tags/', '/category/', '/chuyen-muc/', '/dieu-khoan', '/lien-he', '/gioi-thieu',
  '/rss', '/video', '/videos', '/photo', '/photos', '/infographic', '/quizz', '/login', '/dang-nhap',
  '/dang-ky', 'facebook.com', 'twitter.com', 'youtube.com', 'zalo.me', 'linkedin.com', 'tiktok.com',
  'javascript:', 'mailto:', 'tel:', '#', 'tuyen-dung', '/search', 'adsfw', 'mode=default', 'mobile=yes',
  '/terms', '/privacy', '/contact', '/about', '/author/', '/user/', '/cdn-cgi/'
];

const candidateLinks = [];
const seen = new Set();
const currentSourceUrlClean = (currentSource.url || '').replace(/\\/+$/, '');

for (const raw of rawLinks) {
  const parsed = parseUrlString(raw, currentOrigin);
  if (!parsed) continue;

  const fullUrl = parsed.full;

  // Bỏ qua nếu là chính URL trang danh mục
  if (fullUrl.replace(/\\/+$/, '') === currentSourceUrlClean) continue;
  if (assetRegex.test(fullUrl)) continue;
  if (excludePatterns.some(p => fullUrl.toLowerCase().includes(p))) continue;

  const host = parsed.host;
  const pathname = parsed.pathname;
  const search = parsed.search;

  let isArticle = false;

  // Lọc theo các nguồn đã biết
  if (host.includes('vsdc.vn')) {
    isArticle = /\/vi\/(ad|tin-tuc|tin-thi-truong-co-so)\/\d+/.test(pathname) || /\/vi\/ad\/\d+/.test(pathname) || (pathname.includes('/vi/') && /\d{3,}/.test(pathname) && pathname.length > 20);
  } else if (host.includes('congbothongtin.ssc.gov.vn')) {
    isArticle = pathname.includes('/tin-tuc/') || pathname.includes('/cong-bo/') || search.includes('id=') || /\/\d+$/.test(pathname) || (pathname.split('/').length > 2 && pathname.length > 15);
  } else if (host.includes('ssc.gov.vn')) {
    isArticle = search.includes('dDocName=') || search.includes('dDocName') || pathname.includes('/detail/') || pathname.includes('/tin-tuc/') || pathname.includes('/tintuc/');
  } else if (host.includes('baochinhphu.vn')) {
    isArticle = /\-[0-9]{5,}\.htm/i.test(pathname);
  } else if (host.includes('vanban.chinhphu.vn')) {
    isArticle = search.includes('docid=');
  } else if (host.includes('chinhphu.vn')) {
    isArticle = /\-[0-9]{4,}/.test(pathname) || search.includes('docid=') || pathname.includes('/chi-tiet-tin/');
  } else if (host.includes('vnbusiness.vn')) {
    const slug = pathname.replace(/^\//, '').replace(/\.html$/, '');
    isArticle = pathname.endsWith('.html') && 
                slug.length >= 15 && 
                !['tai-chinh', 'chung-khoan', 'doanh-nghiep', 'kinh-te', 'thi-truong', 'ngan-hang', 'bat-dong-san'].includes(slug);
  } else if (host.includes('thoibaotaichinhvietnam.vn')) {
    isArticle = /\-[0-9]+\.html$/i.test(pathname);
  } else if (host.includes('cnbc.com')) {
    isArticle = /\/\d{4}\/\d{2}\/\d{2}\/[a-zA-Z0-9-]+\.html/i.test(pathname) || (pathname.includes('/202') && pathname.endsWith('.html'));
  } else if (host.includes('cnn.com')) {
    isArticle = /\/\d{4}\/\d{2}\/\d{2}\//.test(pathname) || pathname.includes('/economy/') || pathname.includes('/business/');
  } else if (host.includes('bbc.com')) {
    isArticle = pathname.includes('/articles/');
  } else if (host.includes('bloomberg.com')) {
    isArticle = pathname.includes('/articles/') || pathname.includes('/news/');
  } else if (host.includes('wsj.com')) {
    isArticle = pathname.includes('/articles/') || /\/\d{4}\/\d{2}\/\d{2}\//.test(pathname);
  } else if (host.includes('ft.com')) {
    isArticle = pathname.includes('/content/') || pathname.includes('/tearsheet/') || /\/[a-f0-9-]{36}/.test(pathname) || pathname.includes('/data/equities/');
  } else {
    // Bộ lọc thông minh TỔNG QUÁT cho MỌI NGUỒN MỚI
    const sourceDomain = currentOrigin.replace(/^https?:\\/\\//, '').split(':')[0].toLowerCase();
    const isSameHost = host.includes(sourceDomain) || sourceDomain.includes(host);
    const hasArticleExt = pathname.endsWith('.html') || pathname.endsWith('.htm') || pathname.endsWith('.chn');
    const hasArticlePattern = /\\/\\d{4}\\/\\d{2}\\//.test(pathname) || /\\-[0-9]{4,}/.test(pathname) || /\\/tin-tuc\\/|\\/bai-viet\\/|\\/post\\//.test(pathname);
    const slugLength = pathname.replace(/^\\/|\\/$/g, '').length;
    isArticle = isSameHost && (hasArticleExt || hasArticlePattern || (slugLength >= 18 && pathname.includes('-')));
  }

  if (isArticle && !seen.has(fullUrl)) {
    seen.add(fullUrl);
    candidateLinks.push(fullUrl);
  }
}

// Giới hạn tối đa 10 bài viết mới nhất mỗi lần quét nguồn
const topLinks = candidateLinks.slice(0, 10);

return [{
  json: {
    source_id: currentSource.id,
    source_name: currentSource.name,
    source_category: currentSource.cat,
    source_url: currentSource.url,
    candidate_urls: topLinks,
    has_candidates: topLinks.length > 0
  }
}];"""
                },
                "id": "filter-article-links",
                "name": "4. Lọc URL Bài Viết (Code)",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [980, 340]
            },
            {
                "parameters": {
                    "conditions": {
                        "options": {
                            "caseSensitive": True,
                            "leftValue": "",
                            "typeValidation": "loose"
                        },
                        "conditions": [
                            {
                                "id": "cond-has-cand",
                                "leftValue": "={{ ($json.candidate_urls || []).length }}",
                                "rightValue": 0,
                                "operator": {
                                    "type": "number",
                                    "operation": "gt"
                                }
                            }
                        ],
                        "combinator": "and"
                    },
                    "options": {}
                },
                "id": "check-has-candidates",
                "name": "5. Có Link Bài Viết Không?",
                "type": "n8n-nodes-base.if",
                "typeVersion": 2,
                "position": [1200, 340]
            },
            {
                "parameters": {
                    "operation": "executeQuery",
                    "query": "=SELECT url FROM public.crawled_articles WHERE url IN ({{ ($json.candidate_urls && $json.candidate_urls.length > 0) ? $json.candidate_urls.map(u => \"'\" + u.replace(/'/g, \"''\") + \"'\").join(',') : \"''\" }});"
                },
                "id": "check-existing-urls",
                "name": "6. Kiểm tra URL đã có trong DB (Postgres)",
                "type": "n8n-nodes-base.postgres",
                "typeVersion": 2.5,
                "position": [1420, 240],
                "alwaysOutputData": True,
                "credentials": {
                    "postgres": {
                        "id": "sHxc5RWg5GkqDMcY",
                        "name": "Postgres account"
                    }
                },
                "onError": "continueRegularOutput"
            },
            {
                "parameters": {
                    "jsCode": """let sourceInfo = {};
try {
  sourceInfo = $('5. Có Link Bài Viết Không?').last().json;
} catch (e) {
  try {
    sourceInfo = $('4. Lọc URL Bài Viết (Code)').last().json;
  } catch (err) {
    sourceInfo = $input.first().json;
  }
}

const candidateUrls = sourceInfo.candidate_urls || [];
const dbItems = $input.all();

const existingUrls = new Set();
for (const item of dbItems) {
  if (item.json?.url) {
    existingUrls.add(item.json.url.trim());
  }
}

// Lọc ra các URL chưa từng có trong DB
const newUrls = candidateUrls.filter(u => !existingUrls.has(u));

return [{
  json: {
    source_id: sourceInfo.source_id,
    source_name: sourceInfo.source_name,
    source_category: sourceInfo.source_category,
    source_url: sourceInfo.source_url,
    candidate_urls: candidateUrls,
    new_urls: newUrls,
    has_new_articles: newUrls.length > 0
  }
}];"""
                },
                "id": "filter-uncrawled-only",
                "name": "7. Lọc Link Mới Chưa Cào (Code)",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [1640, 240]
            },
            {
                "parameters": {
                    "conditions": {
                        "options": {
                            "caseSensitive": True,
                            "leftValue": "",
                            "typeValidation": "loose"
                        },
                        "conditions": [
                            {
                                "id": "cond-has-new",
                                "leftValue": "={{ ($json.new_urls || []).length }}",
                                "rightValue": 0,
                                "operator": {
                                    "type": "number",
                                    "operation": "gt"
                                }
                            }
                        ],
                        "combinator": "and"
                    },
                    "options": {}
                },
                "id": "check-has-new",
                "name": "8. Có bài mới cần cào không?",
                "type": "n8n-nodes-base.if",
                "typeVersion": 2,
                "position": [1860, 240]
            },
            {
                "parameters": {
                    "jsCode": """const info = $input.first().json;
const urls = info.new_urls || [];

return urls.map(u => ({
  json: {
    article_url: u,
    source_id: info.source_id,
    source_name: info.source_name,
    source_category: info.source_category,
    source_url: info.source_url
  }
}));"""
                },
                "id": "split-new-urls",
                "name": "9. Tách từng Bài Viết Mới (Code)",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [2080, 160]
            },
            {
                "parameters": {
                    "method": "POST",
                    "url": "http://crawl4ai:11235/crawl",
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [
                            {
                                "name": "Authorization",
                                "value": "Bearer crawl4ai_secret_token_2026"
                            },
                            {
                                "name": "Content-Type",
                                "value": "application/json"
                            }
                        ]
                    },
                    "sendBody": True,
                    "specifyBody": "json",
                    "jsonBody": "={{\n  JSON.stringify({\n    urls: [ $json.article_url || $('9. Tách từng Bài Viết Mới (Code)').item.json.article_url ],\n    priority: 10,\n    crawler_params: {\n      headless: true,\n      magic: true,\n      word_count_threshold: 20,\n      excluded_tags: [\n        \"nav\", \"footer\", \"header\", \"aside\", \"form\", \n        \"script\", \"style\", \"noscript\", \"svg\", \"button\", \n        \"iframe\", \"menu\", \"dialog\"\n      ],\n      exclude_social_media_links: true,\n      remove_overlay_elements: true,\n      keep_data_attributes: false\n    },\n    crawler_config: {\n      type: \"CrawlerRunConfig\",\n      params: {\n        word_count_threshold: 20,\n        excluded_tags: [\n          \"nav\", \"footer\", \"header\", \"aside\", \"form\", \n          \"script\", \"style\", \"noscript\", \"svg\", \"button\", \n          \"iframe\", \"menu\", \"dialog\"\n        ],\n        exclude_social_media_links: true,\n        remove_overlay_elements: true,\n        keep_data_attributes: false,\n        markdown_generator: {\n          type: \"DefaultMarkdownGenerator\",\n          params: {\n            content_filter: {\n              type: \"PruningContentFilter\",\n              params: {\n                threshold: 0.45\n              }\n            }\n          }\n        }\n      }\n    }\n  })\n}}",
                    "options": {
                        "timeout": 60000,
                        "response": {
                            "response": {
                                "responseFormat": "json"
                            }
                        }
                    }
                },
                "id": "scrape-article-content",
                "name": "10. Cào Toàn Văn Bài Báo (Crawl4AI)",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [2320, 160],
                "onError": "continueRegularOutput"
            },
            {
                "parameters": {
                    "jsCode": """// Node 11: Chuẩn hóa & Trích xuất Chi tiết Bài Báo (Lọc sạch rác, header, footer, HTML 100%)
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

// Hàm làm sạch triệt để Markdown: Xóa thẻ HTML sót lại, menu links, disclaimer, footer báo chí
function cleanMarkdownContent(text) {
  if (!text) return '';
  
  let cleaned = text
    // Xóa thẻ HTML còn sót: <div...>, <span>, <p>, v.v.
    .replace(/<[^>]+>/g, '')
    // Xóa các link chia sẻ mạng xã hội
    .replace(/\\[?(?:Chia sẻ|Share|Facebook|Twitter|Zalo|LinkedIn|Pinterest|Copy link)\\]?(?:\\([^)]+\\))?/gi, '')
    // Xóa các dòng menu điều hướng (dạng: [Trang chủ](url) / [Kinh doanh](url)...)
    .replace(/^.*(?:\\[Trang chủ\\]|\\[Tin tức\\]|\\[Kinh doanh\\]|\\[Chứng khoán\\]).*$/gim, '')
    // Xóa các khối thông tin bản quyền, giấy phép báo chí cuối trang
    .replace(/(?:Bản quyền thuộc|Cơ quan chủ quản|Giấy phép xuất bản|Tổng biên tập|Tòa soạn:|Hotline:|Liên hệ quảng cáo|Ghi rõ nguồn|Theo dõi trên Google News)[\\s\\S]*$/gi, '')
    // Xóa các liên kết bài đọc thêm / liên quan
    .replace(/^[*\s-]*(?:Đọc thêm|Xem thêm|Tin liên quan|Bài liên quan|Cùng chuyên mục)[\\s\\S]*?(?=\\n\\n|$)/gim, '')
    // Chuẩn hóa khoảng trắng và dòng trống
    .replace(/\\n{3,}/g, '\\n\\n')
    .trim();

  return cleaned;
}

for (let i = 0; i < inputItems.length; i++) {
  let crawlItem = inputItems[i].json || {};
  if (typeof crawlItem === 'string') {
    try { crawlItem = JSON.parse(crawlItem); } catch(e) {}
  }
  if (typeof crawlItem.data === 'string') {
    try { crawlItem = JSON.parse(crawlItem.data); } catch(e) {}
  }

  const currentArticle = newUrlItems[i]?.json || {};
  
  const crawlRes = (Array.isArray(crawlItem.results) ? crawlItem.results[0] : (crawlItem.result || crawlItem.data || crawlItem)) || {};
  const metadata = crawlRes.metadata || {};
  const mdObj = crawlRes.markdown || {};
  
  const articleUrl = currentArticle.article_url || crawlRes.url || metadata.sourceURL || metadata.url || '';
  if (!articleUrl) continue;

  // 1. Ưu tiên lấy fit_markdown của Crawl4AI (đã lọc nội dung chính)
  let rawText = '';
  if (typeof mdObj === 'string') {
    rawText = mdObj;
  } else if (mdObj.fit_markdown && mdObj.fit_markdown.trim().length > 80) {
    rawText = mdObj.fit_markdown;
  } else if (mdObj.raw_markdown) {
    rawText = mdObj.raw_markdown;
  } else if (crawlRes.content) {
    rawText = crawlRes.content;
  }

  let cleanContent = cleanMarkdownContent(rawText);

  // 2. Tiêu đề bài viết (Thông minh: hỗ trợ văn bản cơ quan nhà nước, UBCKNN, Chính phủ)
  let title = '';
  const blacklist = [
    'tin tức', 'thống kê', 'tin cùng tổ chức', 'tin khác', 'menu', 'trang chủ', 
    'bình luận', 'ý kiến', 'văn bản mới', 'danh mục', 'chi tiết', 
    'các tin khác', 'bình chọn', 'liên kết', 'tìm kiếm', 'giới thiệu', 'chức năng', 'chuyên mục'
  ];
  
  if (cleanContent) {
    const allHeadings = cleanContent.match(/^#{1,3}\\s+(.+)$/gm) || [];
    for (const h of allHeadings) {
      const cand = h.replace(/^#{1,3}\\s+/, '').replace(/\\[([^\\]]+)\\]\\([^)]+\\)/g, '$1').replace(/[*_`]/g, '').trim();
      const lower = cand.toLowerCase();
      if (cand.length >= 12 && !blacklist.some(b => lower === b || lower === (b + ':'))) {
        title = cand;
        break;
      }
    }
  }

  // Cắt bỏ phần menu điều hướng rác ở đầu trang nếu tìm thấy tiêu đề
  if (title && cleanContent.includes(title)) {
    const titleIdx = cleanContent.indexOf(title);
    if (titleIdx > 150) {
      cleanContent = cleanContent.slice(titleIdx).trim();
    }
  }

  if (!title) {
    title = metadata.ogTitle || metadata['og:title'] || metadata.title || metadata.its_title || metadata.headline || '';
  }
  title = title.replace(/\\s*[-|–—]\\s*(?:Báo\\s+|Trang tin\\s+|Cổng TT\\s+)?[A-ZÀ-Ỹa-zà-ỹ0-9\\s\\.]+(?:\\.vn|\\.com|\\.net)?$/i, '').trim();
  if (!title) {
    title = 'Bài viết từ ' + (currentArticle.source_name || sourceInfo.source_name || 'Nguồn tin');
  }

  // 3. Ngày xuất bản
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

  if (!publishedDate && cleanContent) {
    const dMatch = cleanContent.match(/(?:cập nhật ngày|ngày đăng|đăng ngày|thời gian|ngày|xuất bản)[\\s:]*([0-3]?[0-9][\\/\\-\\.][0-1]?[0-9][\\/\\-\\.][1-2][0-9]{3}(?:\\s*[\\-,]?\\s*[0-2]?[0-9]:[0-5][0-9](?::[0-5][0-9])?)?)/i);
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

  // 4. Tác giả
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

  if (!author && cleanContent) {
    const authorMatch = cleanContent.match(/(?:^|\\n)\\s*(?:Bài và ảnh|Ảnh|Theo|Nguồn|Nguồn tin|Tác giả|Phóng viên|Ký giả|PV)[\\s:]+([A-ZÀ-Ỹa-zà-ỹ0-9\\s\\.\\-]{3,60})(?:\\n|$)/i);
    if (authorMatch) {
      author = authorMatch[1].trim();
    } else {
      const boldAuthorMatch = cleanContent.match(/(?:^|\\n)\\s*\\*{1,2}([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})\\*{1,2}\\s*(?:\\([^\\)]+\\))?\\s*$/m);
      if (boldAuthorMatch) {
        author = boldAuthorMatch[1].trim();
      }
    }
  }
  if (!author) {
    author = currentArticle.source_name || sourceInfo.source_name || metadata.ogSiteName || metadata.source || 'Ban Biên Tập';
  }

  // 5. Tóm tắt
  let summary = metadata.description || metadata.ogDescription || metadata['og:description'] || metadata['twitter:description'] || '';
  if (summary) {
    summary = summary.replace(/^[-—|\\s]+/, '').trim();
  }
  if (!summary || summary.length < 30) {
    if (cleanContent) {
      const paragraphs = cleanContent.split(/\\n\\s*\\n/).map(p => p.trim()).filter(p => p.length > 40 && !p.startsWith('#') && !p.startsWith('Ảnh:'));
      if (paragraphs.length > 0) {
        summary = paragraphs[0].slice(0, 350).trim();
        if (paragraphs[0].length > 350) summary += '...';
      }
    }
  }
  if (!summary) {
    summary = 'Nội dung cập nhật từ ' + (currentArticle.source_name || sourceInfo.source_name || 'nguồn tin');
  }

  // 6. Tags, Điểm chính & Cảm xúc
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
  if (cleanContent) {
    const bulletMatches = cleanContent.match(/^[*-]\\s+([^\\n]+)$/gm);
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
    keywords: tags
  };

  const cleanTitle = (title || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\\u0300-\\u036f]/g, '')
    .replace(/[^a-z0-9\\s]/g, '')
    .replace(/\\s+/g, ' ')
    .trim();

  const titleHash = createHash(cleanTitle);

  if (cleanContent.length < 50 && (!title || title.startsWith('Bài viết từ'))) {
    continue; // Bỏ qua không lưu bài lỗi / bài rỗng vào database
  }

  results.push({
    json: {
      title: title.trim(),
      url: articleUrl,
      summary: summary.trim(),
      content_raw: cleanContent.slice(0, 50000),
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

return results;"""
                },
                "id": "format-and-clean-article",
                "name": "11. Chuẩn hóa & Trích xuất Chi tiết (Code)",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [2580, 160]
            },
            {
                "parameters": {
                    "operation": "executeQuery",
                    "query": """=INSERT INTO public.crawled_articles (
  url, title, summary, content_raw, published_date, author,
  source_name, source_category, source_url, tags, sentiment, metadata
)
VALUES (
  '{{ $json.url }}',
  '{{ ($json.title || "").replace(/'/g, "''") }}',
  '{{ ($json.summary || "").replace(/'/g, "''") }}',
  '{{ ($json.content_raw || "").replace(/'/g, "''") }}',
  {{ $json.published_date ? "'" + $json.published_date + "'::timestamptz" : "NULL" }},
  '{{ ($json.author || "").replace(/'/g, "''") }}',
  '{{ ($json.source_name || "").replace(/'/g, "''") }}',
  '{{ ($json.source_category || "").replace(/'/g, "''") }}',
  '{{ ($json.source_url || "").replace(/'/g, "''") }}',
  ARRAY[{{ ($json.tags || []).map(t => "'" + t.replace(/'/g, "''") + "'").join(',') }}]::text[],
  '{{ $json.sentiment || "Trung lập" }}',
  '{{ JSON.stringify($json.structured_data || {}).replace(/'/g, "''") }}'::jsonb
)
ON CONFLICT (url) DO UPDATE SET
  title = EXCLUDED.title,
  summary = EXCLUDED.summary,
  content_raw = EXCLUDED.content_raw,
  published_date = COALESCE(EXCLUDED.published_date, public.crawled_articles.published_date),
  author = COALESCE(NULLIF(EXCLUDED.author, ''), public.crawled_articles.author),
  tags = EXCLUDED.tags,
  sentiment = EXCLUDED.sentiment,
  metadata = EXCLUDED.metadata,
  updated_at = CURRENT_TIMESTAMP;"""
                },
                "id": "save-article-to-db",
                "name": "12. Lưu Bài Báo (Postgres)",
                "type": "n8n-nodes-base.postgres",
                "typeVersion": 2.5,
                "position": [2820, 160],
                "credentials": {
                    "postgres": {
                        "id": "sHxc5RWg5GkqDMcY",
                        "name": "Postgres account"
                    }
                }
            },
            {
                "parameters": {
                    "jsCode": """// Node 13: Báo hoàn tất cào toàn bộ bài viết của nguồn này (gom lại 1 item duy nhất để trigger tiếp nguồn sau)
return [{
  json: {
    status: 'articles_batch_completed',
    processed_count: $input.all().length
  }
}];"""
                },
                "id": "source-articles-completed",
                "name": "13. Hoàn tất Cào Nguồn (Code)",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [3060, 160]
            },
            {
                "parameters": {
                    "operation": "executeQuery",
                    "query": "=UPDATE public.crawl_targets SET last_crawled_at = NOW(), last_status = 'success' WHERE id = {{ $('4. Lọc URL Bài Viết (Code)').last().json.source_id }};"
                },
                "id": "update-source-timestamp",
                "name": "14. Cập nhật Lịch Cào Nguồn (Postgres)",
                "type": "n8n-nodes-base.postgres",
                "typeVersion": 2.5,
                "position": [3300, 240],
                "credentials": {
                    "postgres": {
                        "id": "sHxc5RWg5GkqDMcY",
                        "name": "Postgres account"
                    }
                }
            },
            {
                "parameters": {},
                "id": "trigger-add-source-manual",
                "name": "Bấm để Thêm Nguồn (Manual Trigger)",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [100, 620]
            },
            {
                "parameters": {
                    "jsCode": """// Khai báo nguồn cần thêm
return [
  {
    json: {
      source_name: 'VnExpress - Kinh doanh',
      source_category: 'Báo Tài chính VN',
      source_url: 'https://vnexpress.net/kinh-doanh'
    }
  }
];"""
                },
                "id": "define-new-sources",
                "name": "Khai báo Nguồn Cần Thêm (Code)",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [340, 620]
            },
            {
                "parameters": {
                    "httpMethod": "POST",
                    "path": "them-nguon-tin",
                    "options": {}
                },
                "id": "webhook-add-source",
                "name": "Webhook Thêm Nguồn (POST)",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [100, 780]
            },
            {
                "parameters": {
                    "operation": "executeQuery",
                    "query": """=INSERT INTO public.crawl_targets (source_name, source_category, source_url, active, last_status)
VALUES (
  '{{ ($json.body?.source_name || $json.source_name || '').replace(/'/g, "''") }}',
  '{{ ($json.body?.source_category || $json.source_category || 'Tài chính').replace(/'/g, "''") }}',
  '{{ ($json.body?.source_url || $json.source_url || '').trim().replace(/'/g, "''") }}',
  true,
  'pending'
)
ON CONFLICT (source_url) DO UPDATE
SET source_name = EXCLUDED.source_name,
    source_category = EXCLUDED.source_category,
    active = true,
    last_status = 'pending'
RETURNING id, source_name, source_category, source_url, active, last_status;"""
                },
                "id": "save-source-to-db",
                "name": "Lưu Nguồn Vào Database (Postgres)",
                "type": "n8n-nodes-base.postgres",
                "typeVersion": 2.5,
                "position": [580, 680],
                "credentials": {
                    "postgres": {
                        "id": "sHxc5RWg5GkqDMcY",
                        "name": "Postgres account"
                    }
                }
            }
        ],
        "connections": {
            "Khi bấm Test (Manual Trigger)": {
                "main": [
                    [{"node": "1. Lấy Danh Sách Trang Danh Mục (Postgres)", "type": "main", "index": 0}]
                ]
            },
            "Lập lịch định kỳ (Mỗi 30 phút)": {
                "main": [
                    [{"node": "1. Lấy Danh Sách Trang Danh Mục (Postgres)", "type": "main", "index": 0}]
                ]
            },
            "1. Lấy Danh Sách Trang Danh Mục (Postgres)": {
                "main": [
                    [{"node": "2. Duyệt từng Nguồn Danh Mục", "type": "main", "index": 0}]
                ]
            },
            "2. Duyệt từng Nguồn Danh Mục": {
                "main": [
                    [],
                    [{"node": "3. Cào Links Danh Mục (Crawl4AI)", "type": "main", "index": 0}]
                ]
            },
            "3. Cào Links Danh Mục (Crawl4AI)": {
                "main": [
                    [{"node": "4. Lọc URL Bài Viết (Code)", "type": "main", "index": 0}]
                ]
            },
            "4. Lọc URL Bài Viết (Code)": {
                "main": [
                    [{"node": "5. Có Link Bài Viết Không?", "type": "main", "index": 0}]
                ]
            },
            "5. Có Link Bài Viết Không?": {
                "main": [
                    [{"node": "6. Kiểm tra URL đã có trong DB (Postgres)", "type": "main", "index": 0}],
                    [{"node": "14. Cập nhật Lịch Cào Nguồn (Postgres)", "type": "main", "index": 0}]
                ]
            },
            "6. Kiểm tra URL đã có trong DB (Postgres)": {
                "main": [
                    [{"node": "7. Lọc Link Mới Chưa Cào (Code)", "type": "main", "index": 0}]
                ]
            },
            "7. Lọc Link Mới Chưa Cào (Code)": {
                "main": [
                    [{"node": "8. Có bài mới cần cào không?", "type": "main", "index": 0}]
                ]
            },
            "8. Có bài mới cần cào không?": {
                "main": [
                    [{"node": "9. Tách từng Bài Viết Mới (Code)", "type": "main", "index": 0}],
                    [{"node": "14. Cập nhật Lịch Cào Nguồn (Postgres)", "type": "main", "index": 0}]
                ]
            },
            "9. Tách từng Bài Viết Mới (Code)": {
                "main": [
                    [{"node": "10. Cào Toàn Văn Bài Báo (Crawl4AI)", "type": "main", "index": 0}]
                ]
            },
            "10. Cào Toàn Văn Bài Báo (Crawl4AI)": {
                "main": [
                    [{"node": "11. Chuẩn hóa & Trích xuất Chi tiết (Code)", "type": "main", "index": 0}]
                ]
            },
            "11. Chuẩn hóa & Trích xuất Chi tiết (Code)": {
                "main": [
                    [{"node": "12. Lưu Bài Báo (Postgres)", "type": "main", "index": 0}]
                ]
            },
            "12. Lưu Bài Báo (Postgres)": {
                "main": [
                    [{"node": "13. Hoàn tất Cào Nguồn (Code)", "type": "main", "index": 0}]
                ]
            },
            "13. Hoàn tất Cào Nguồn (Code)": {
                "main": [
                    [{"node": "14. Cập nhật Lịch Cào Nguồn (Postgres)", "type": "main", "index": 0}]
                ]
            },
            "14. Cập nhật Lịch Cào Nguồn (Postgres)": {
                "main": [
                    [{"node": "2. Duyệt từng Nguồn Danh Mục", "type": "main", "index": 0}]
                ]
            },
            "Bấm để Thêm Nguồn (Manual Trigger)": {
                "main": [
                    [{"node": "Khai báo Nguồn Cần Thêm (Code)", "type": "main", "index": 0}]
                ]
            },
            "Khai báo Nguồn Cần Thêm (Code)": {
                "main": [
                    [{"node": "Lưu Nguồn Vào Database (Postgres)", "type": "main", "index": 0}]
                ]
            },
            "Webhook Thêm Nguồn (POST)": {
                "main": [
                    [{"node": "Lưu Nguồn Vào Database (Postgres)", "type": "main", "index": 0}]
                ]
            }
        },
        "settings": {
            "executionOrder": "v1"
        }
    }

    target_path = "/Users/doveun/Documents/Project/BigData/stock-news-mvp/crawl4ai/workflow_crawl4ai_news_pipeline.json"
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False, indent=2)
    print("SUCCESS: File workflow written successfully!")

if __name__ == "__main__":
    build_workflow()
