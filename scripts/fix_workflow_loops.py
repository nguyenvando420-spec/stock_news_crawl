import json

with open('n8n_news_aggregator_workflow.json', 'r', encoding='utf-8') as f:
    wf = json.load(f)

for node in wf.get('nodes', []):
    name = node.get('name')
    params = node.get('parameters', {})
    
    # Node 4: Sửa fallback từ .first() sang .last()
    if name == '4. Lọc URL Bài Viết (Code)' and 'jsCode' in params:
        code = params['jsCode']
        code = code.replace(".first().json;", ".last().json;")
        params['jsCode'] = code
        print('Updated Node 4 fallback to .last()')
        
    # Node 7: Sửa lấy nguồn từ .first() sang .last()
    if name == '7. Lọc Link Mới Chưa Cào (Code)' and 'jsCode' in params:
        code = params['jsCode']
        code = code.replace("$('5. Có Link Bài Viết Không?').first().json;", "$('5. Có Link Bài Viết Không?').last().json;")
        code = code.replace("$('4. Lọc URL Bài Viết (Code)').first().json;", "$('4. Lọc URL Bài Viết (Code)').last().json;")
        params['jsCode'] = code
        print('Updated Node 7 to .last()')

    # Node 13: Sửa fallback từ .first() sang .last()
    if name == '13. Chuẩn hóa & Trích xuất Chi tiết (Code)' and 'jsCode' in params:
        code = params['jsCode']
        code = code.replace("$('10. Duyệt từng Bài Viết Mới').first().json;", "$('10. Duyệt từng Bài Viết Mới').last().json;")
        params['jsCode'] = code
        print('Updated Node 13 fallback to .last()')

    # Node 15: Sửa update ID nguồn từ .first() sang .last()
    if name == '15. Cập nhật Lịch Cào Nguồn (Postgres)' and 'query' in params:
        code = params['query']
        code = code.replace(".first().json.source_id", ".last().json.source_id")
        params['query'] = code
        print('Updated Node 15 to .last()')

with open('n8n_news_aggregator_workflow.json', 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print('Done updating n8n_news_aggregator_workflow.json')
