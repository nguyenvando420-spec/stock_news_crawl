import json
import os

workflow_path = '/Users/doveun/Documents/Project/BigData/stock-news-mvp/n8n_news_aggregator_workflow.json'

with open(workflow_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

for node in wf['nodes']:
    # 1. Update Node 3: Cào Links từ Trang Danh Mục (Firecrawl)
    if node['id'] == 'scrape-links':
        node['parameters']['jsonBody'] = (
            '={\n'
            '  "url": "{{ $json.source_url }}",\n'
            '  "formats": ["links", "markdown"],\n'
            '  "waitFor": {{ $json.source_url && $json.source_url.includes("congbothongtin.ssc.gov.vn") ? 5000 : 0 }},\n'
            '  "timeout": 45000,\n'
            '  "headers": {\n'
            '    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",\n'
            '    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",\n'
            '    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8"\n'
            '  }\n'
            '}'
        )
        print('Updated Node 3 (scrape-links)')

    # 2. Update Node 4: Lọc URL Bài Viết (Code)
    if node['id'] == 'filter-article-links':
        code = node['parameters']['jsCode']
        ssc_handler = '''// XỬ LÝ ĐẶC THÙ CHO CỔNG CÔNG BỐ THÔNG TIN UBCKNN (congbothongtin.ssc.gov.vn)
if (currentOrigin.includes('congbothongtin.ssc.gov.vn') || (currentSource.url && currentSource.url.includes('congbothongtin.ssc.gov.vn'))) {
  let md = '';
  for (const item of allInputItems) {
    if (item.json?.markdown) md = item.json.markdown;
    if (item.json?.data?.markdown) md = item.json.data.markdown;
  }
  
  const preParsed = {};
  const sscCandidates = [];
  
  if (md) {
    const lines = md.split('\\n');
    for (const line of lines) {
      const s = line.trim();
      if (s.startsWith('|') && s.endsWith('|')) {
        const cols = s.split('|').slice(1, -1).map(c => c.trim());
        if (cols.length >= 5 && /^\\d+$/.test(cols[0]) && !s.includes('Go To Page')) {
          const stt = cols[0];
          
          // Case 1: CompanyProfilesSearch (Danh sách Công ty đại chúng)
          if (currentSource.url.includes('CompanyProfilesSearch')) {
            const name = cols[1].replace(/\\[(.*?)\\]\\(.*?\\)/g, '$1').trim();
            const taxId = cols[2];
            const exchange = cols[3];
            const stockCode = cols[4];
            const cleanTitle = `[${exchange}: ${stockCode}] Hồ sơ Công ty đại chúng - ${name}`;
            const articleUrl = `https://congbothongtin.ssc.gov.vn/faces/CompanyProfilesSearch#cty-${stockCode.toLowerCase()}-${taxId}`;
            preParsed[articleUrl] = {
              title: cleanTitle,
              url: articleUrl,
              summary: `Công ty đại chúng ${name}, Mã số DN: ${taxId}, Niêm yết sàn ${exchange}, Mã CK: ${stockCode}.`,
              content_raw: `# ${cleanTitle}\\n\\n**Tên công ty:** ${name}\\n**Mã số doanh nghiệp:** ${taxId}\\n**Sàn giao dịch:** ${exchange}\\n**Mã chứng khoán:** ${stockCode}`,
              company_name: name,
              stock_code: stockCode,
              exchange: exchange,
              tags: ['UBCKNN', 'Công ty đại chúng', exchange, stockCode],
              published_date: new Date().toISOString()
            };
            sscCandidates.push(articleUrl);
          }
          // Case 2: CompanyAuditingSearch (Tổ chức kiểm toán chấp thuận)
          else if (currentSource.url.includes('CompanyAuditingSearch')) {
            const shortName = cols[1];
            const fullName = cols[2].replace(/\\[(.*?)\\]\\(.*?\\)/g, '$1').trim();
            const website = cols[3];
            const capital = cols[4];
            const phone = cols[5];
            const cleanTitle = `Tổ chức kiểm toán chấp thuận: ${fullName} (${shortName})`;
            const cleanShort = (shortName || 'aud').toLowerCase().replace(/[^a-z0-9]/g, '');
            const articleUrl = `https://congbothongtin.ssc.gov.vn/faces/CompanyAuditingSearch#audit-${stt}-${cleanShort}`;
            preParsed[articleUrl] = {
              title: cleanTitle,
              url: articleUrl,
              summary: `Tổ chức kiểm toán được UBCKNN chấp thuận: ${fullName}, Tên viết tắt: ${shortName}, Website: ${website}, Vốn điều lệ: ${capital}, SĐT: ${phone}.`,
              content_raw: `# ${cleanTitle}\\n\\n**Tên đầy đủ:** ${fullName}\\n**Tên viết tắt:** ${shortName}\\n**Website:** ${website}\\n**Vốn điều lệ:** ${capital}\\n**Số điện thoại:** ${phone}`,
              company_name: fullName,
              tags: ['UBCKNN', 'Công ty kiểm toán', shortName].filter(Boolean),
              published_date: new Date().toISOString()
            };
            sscCandidates.push(articleUrl);
          }
          // Case 3: NewsSearch / Trang chủ (Công bố thông tin)
          else {
            const san = cols[1];
            const mck = cols[2];
            const reportName = cols[3].replace(/\\[(.*?)\\]\\(.*?\\)/g, '$1').trim();
            const donVi = cols[4];
            const trichYeu = (cols[5] && cols[5] !== '&nbsp;') ? cols[5] : '';
            const ngay = cols[6] || '';
            
            let pubDate = null;
            const dMatch = ngay.match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})/);
            if (dMatch) {
              pubDate = `${dMatch[3]}-${dMatch[2]}-${dMatch[1]}T07:00:00+07:00`;
            }
            
            const cleanTitle = `[${san}: ${mck}] ${reportName} - ${donVi}`;
            const summary = trichYeu.length > 10 ? trichYeu : `${reportName} do ${donVi} (Mã CK: ${mck}, Sàn: ${san}) công bố ngày ${ngay}.`;
            const hash = Math.abs((mck + reportName + ngay).split('').reduce((a,b)=>{a=((a<<5)-a)+b.charCodeAt(0);return a&a},0)).toString(16);
            const articleUrl = `https://congbothongtin.ssc.gov.vn/#cbtt-${mck.toLowerCase()}-${hash}`;
            
            preParsed[articleUrl] = {
              title: cleanTitle,
              url: articleUrl,
              summary: summary,
              content_raw: `# ${cleanTitle}\\n\\n**Sàn niêm yết:** ${san}\\n**Mã CK:** ${mck}\\n**Đơn vị:** ${donVi}\\n**Loại báo cáo:** ${reportName}\\n**Ngày công bố:** ${ngay}\\n\\n**Trích yếu:**\\n${summary}`,
              company_name: donVi,
              stock_code: mck,
              exchange: san,
              report_name: reportName,
              tags: ['UBCKNN', 'Công bố thông tin', san, mck, reportName].filter(Boolean),
              published_date: pubDate
            };
            sscCandidates.push(articleUrl);
          }
        }
      }
    }
  }
  
  const topSscLinks = sscCandidates.slice(0, 15);
  return [{
    json: {
      source_id: currentSource.id,
      source_name: currentSource.name,
      source_category: currentSource.cat,
      source_url: currentSource.url,
      candidate_urls: topSscLinks,
      has_candidates: topSscLinks.length > 0,
      pre_parsed_articles: preParsed
    }
  }];
}
'''
        marker = '// 3. Bộ lọc rác và tài nguyên tĩnh'
        if marker in code:
            code = code.replace(marker, ssc_handler + '\n' + marker)
            node['parameters']['jsCode'] = code
            print('Updated Node 4 (filter-article-links)')
        else:
            print('Warning: Marker not found in Node 4')

    # 3. Update Node 7: Lọc Link Mới Chưa Cào (Code)
    if node['id'] == 'filter-uncrawled-only':
        node['parameters']['jsCode'] = '''let sourceInfo = {};
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
    has_new_articles: newUrls.length > 0,
    pre_parsed_articles: sourceInfo.pre_parsed_articles || {}
  }
}];'''
        print('Updated Node 7 (filter-uncrawled-only)')

    # 4. Update Node 9: Tách từng Bài Viết Mới (Code)
    if node['id'] == 'split-new-urls':
        node['parameters']['jsCode'] = '''const info = $input.first().json;
const urls = info.new_urls || [];
const preParsed = info.pre_parsed_articles || {};

return urls.map(u => ({
  json: {
    article_url: u,
    source_id: info.source_id,
    source_name: info.source_name,
    source_category: info.source_category,
    source_url: info.source_url,
    pre_extracted: preParsed[u] || null
  }
}));'''
        print('Updated Node 9 (split-new-urls)')

    # 5. Update Node 13: Chuẩn hóa & Trích xuất Chi tiết (Code)
    if node['id'] == 'hash-and-format':
        code = node['parameters']['jsCode']
        target_loop_start = 'for (let i = 0; i < inputItems.length; i++) {\n  const firecrawlRes = inputItems[i].json || {};\n  const currentArticle = newUrlItems[i]?.json || {};\n  \n  const metadata = firecrawlRes.data?.metadata || firecrawlRes.metadata || {};'
        
        replacement_loop_start = '''for (let i = 0; i < inputItems.length; i++) {
  const firecrawlRes = inputItems[i].json || {};
  const currentArticle = newUrlItems[i]?.json || {};
  
  // Xử lý bài viết đã được trích xuất dữ liệu sẵn từ bảng (như congbothongtin.ssc.gov.vn)
  if (currentArticle.pre_extracted) {
    const pre = currentArticle.pre_extracted;
    const cat = currentArticle.source_category || sourceInfo.source_category || 'Cơ quan Quản lý & Pháp lý';
    const tags = Array.isArray(pre.tags) ? pre.tags : ['UBCKNN', 'Công bố thông tin'];
    if (!tags.includes(cat)) tags.unshift(cat);
    
    const structuredData = {
      author: pre.company_name || 'UBCKNN',
      published_date: pre.published_date,
      source_name: currentArticle.source_name || sourceInfo.source_name || 'UBCKNN - Công bố',
      source_category: cat,
      language: 'vi',
      canonical_url: pre.url,
      stock_code: pre.stock_code || null,
      exchange: pre.exchange || null,
      report_name: pre.report_name || null,
      keywords: tags
    };
    
    const cleanTitle = (pre.title || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\\u0300-\\u036f]/g, '')
      .replace(/[^a-z0-9\\s]/g, '')
      .replace(/\\s+/g, ' ')
      .trim();
      
    results.push({
      json: {
        title: pre.title,
        url: pre.url,
        summary: pre.summary,
        content_raw: pre.content_raw || pre.summary,
        author: pre.company_name || currentArticle.source_name || 'UBCKNN',
        key_points: [
          `Đơn vị công bố: ${pre.company_name || 'Doanh nghiệp'}`,
          `Nội dung: ${pre.report_name || pre.title}`,
          `Tóm tắt: ${pre.summary}`
        ],
        source_name: currentArticle.source_name || sourceInfo.source_name || 'UBCKNN - Công bố',
        source_category: cat,
        source_url: currentArticle.source_url || sourceInfo.source_url || '',
        sentiment: 'Trung lập',
        tags: tags,
        title_hash: createHash(cleanTitle),
        structured_data: structuredData,
        published_date: pre.published_date
      }
    });
    continue;
  }
  
  const metadata = firecrawlRes.data?.metadata || firecrawlRes.metadata || {};'''
        
        if target_loop_start in code:
            code = code.replace(target_loop_start, replacement_loop_start)
            node['parameters']['jsCode'] = code
            print('Updated Node 13 (hash-and-format)')
        else:
            print('Warning: Target loop start not found in Node 13')

with open(workflow_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, ensure_ascii=False, indent=2)

print('Workflow file successfully updated!')
