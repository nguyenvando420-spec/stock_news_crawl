"""Crawler chuyên dụng cho Cổng công bố thông tin Ủy ban Chứng khoán Nhà nước (UBCKNN).

Kiến trúc nguồn:
- Website: https://congbothongtin.ssc.gov.vn/
- Nền tảng: Oracle ADF / JSF (JavaServer Faces).
- Cơ chế: Form postback theo phiên trình duyệt, click vào từng báo cáo để xem chi tiết
  và lấy nội dung văn bản, ngày ký, số hiệu, mã doanh nghiệp và danh sách file PDF đính kèm.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("crawler.ssc")

SSC_BASE_URL = "https://congbothongtin.ssc.gov.vn"
SSC_SEARCH_URL = f"{SSC_BASE_URL}/faces/NewsSearch"
CHROME_PATH = "/home/appuser/.cache/ms-playwright/chromium-1208/chrome-linux/chrome"


def parse_vn_date(date_str: str) -> Optional[datetime]:
    """Parse ngày định dạng dd/mm/yyyy thành datetime."""
    if not date_str:
        return None
    date_str = date_str.strip()
    # Tìm mẫu dd/mm/yyyy
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_str)
    if m:
        d, mon, y = m.groups()
        try:
            return datetime(int(y), int(mon), int(d))
        except ValueError:
            pass
    return None


async def extract_table_rows(page: Page) -> List[Dict[str, Any]]:
    """Trích xuất danh sách các dòng dữ liệu tóm tắt từ bảng ngoài trang chủ."""
    return await page.evaluate(r"""() => {
        const rows = [];
        const dbDiv = document.querySelector('div[id*="t1::db"]') || document.querySelector('div[id$=":t1::db"]');
        const trs = dbDiv ? Array.from(dbDiv.querySelectorAll('tr')) : [];

        for (let i = 0; i < trs.length; i++) {
            const tr = trs[i];
            const link = tr.querySelector('a[id*="cl1"]');
            if (!link) continue;

            const tds = Array.from(tr.querySelectorAll('td'));
            const stt = tds[0] ? tds[0].innerText.trim() : `${i + 1}`;
            const san = tds[1] ? tds[1].innerText.trim() : '';
            const mck = tds[2] ? tds[2].innerText.trim() : '';
            const title = link ? link.innerText.trim() : (tds[3] ? tds[3].innerText.trim() : '');
            const don_vi = tds[4] ? tds[4].innerText.trim() : '';
            const trich_yeu_table = tds[5] ? tds[5].innerText.trim() : '';
            const thoi_gian_gui = tds[6] ? tds[6].innerText.trim() : '';

            rows.push({
                index: i,
                stt,
                san,
                mck,
                title,
                don_vi,
                trich_yeu_table,
                thoi_gian_gui,
                link_id: link ? link.id : ''
            });
        }
        return rows;
    }""")


async def extract_report_detail(page: Page) -> Dict[str, Any]:
    """Trích xuất chi tiết toàn bộ các trường dữ liệu trên trang báo cáo."""
    return await page.evaluate(r"""() => {
        const text = document.body.innerText;
        
        // 1. Breadcrumb / Chuyên mục
        let category = "Công bố thông tin";
        const breadcrumbMatch = text.match(/Tin công bố\s*\/\s*([^\n\r]+)/);
        if (breadcrumbMatch) {
            category = breadcrumbMatch[1].trim();
        }

        // 2. MDN (Mã doanh nghiệp)
        let mdn = "";
        const mdnMatch = text.match(/MDN\s*([0-9]{8,14})/i);
        if (mdnMatch) {
            mdn = mdnMatch[1].trim();
        }

        // 3. Tên công ty
        let companyName = "";
        const companyMatch = text.match(/Tên công ty\s*([^\n\r]+)/i);
        if (companyMatch) {
            companyName = companyMatch[1].trim();
        }

        // 4. Tiêu đề
        let title = "";
        const titleMatch = text.match(/Tiêu đề\s*([^\n\r]+)/i);
        if (titleMatch) {
            title = titleMatch[1].trim();
        }

        // 5. Các trường Input / Textarea có giá trị
        const formFields = {};
        const inputs = Array.from(document.querySelectorAll('input, textarea'));
        
        // Map label với input gần nhất
        for (const inp of inputs) {
            if (!inp.value || !inp.value.trim()) continue;
            const val = inp.value.trim();
            
            // Tìm label gần đó trong tr hoặc panel
            let label = "";
            let parent = inp.closest('tr') || inp.closest('td') || inp.parentElement;
            if (parent) {
                const labelEl = parent.querySelector('label, span[class*="label"], td[class*="Label"]');
                if (labelEl) {
                    label = labelEl.innerText.replace(/[*:]/g, '').trim();
                }
            }
            if (!label && inp.id) {
                label = inp.id.split(':').pop();
            }
            if (label && !formFields[label]) {
                formFields[label] = val;
            }
        }

        // Trích xuất các trường quan trọng từ văn bản thuần nếu input không có label
        const regexExtract = [
            { key: "Năm tài chính", pattern: /Năm tài chính[\s*]*(\d{4})/i },
            { key: "Quý", pattern: /Quý[\s*]*([1-4])/i },
            { key: "Ngày ký ban hành", pattern: /Ngày ký[^\d]*(\d{1,2}\/\d{1,2}\/\d{4})/i },
            { key: "Ngày phát sinh sự kiện", pattern: /Ngày phát sinh[^\d]*(\d{1,2}\/\d{1,2}\/\d{4})/i },
            { key: "Số văn bản", pattern: /Số văn bản[\s*]*([A-Za-z0-9\/\-_\.]+)/i },
            { key: "Tổ chức kiểm toán", pattern: /Tổ chức kiểm toán[\s*]*([^\n\r]+)/i },
            { key: "Lãnh đạo ký", pattern: /Lãnh đạo ký[^\n\r]*[\s*]*([^\n\r]+)/i },
            { key: "Ý kiến kiểm toán", pattern: /Ý kiến kiểm toán[\s*]*([^\n\r]+)/i },
        ];

        for (const item of regexExtract) {
            if (!formFields[item.key]) {
                const m = text.match(item.pattern);
                if (m) {
                    formFields[item.key] = m[1].trim();
                }
            }
        }

        // 6. Trích yếu / Lý do đính chính
        let trichYeu = "";
        const trichYeuArea = Array.from(document.querySelectorAll('textarea')).find(t => t.id && (t.id.includes('it4') || t.id.includes('trichyeu') || t.id.includes('it21')));
        if (trichYeuArea && trichYeuArea.value.trim()) {
            trichYeu = trichYeuArea.value.trim();
        } else {
            const tyMatch = text.match(/Trích yếu[^\n]*\n+([^\n]+(?:\n[^\n]+){0,5})/i);
            if (tyMatch) {
                trichYeu = tyMatch[1].trim();
            }
        }

        // 7. Danh sách file đính kèm
        const files = [];
        const seenFiles = new Set();
        // Tìm qua text kết thúc bằng .pdf, .docx, .zip
        const fileMatches = text.match(/[0-9A-Za-z_.\-]+\.(?:pdf|docx?|xlsx?|zip)/gi) || [];
        for (const f of fileMatches) {
            const clean = f.trim();
            if (!seenFiles.has(clean.toLowerCase())) {
                seenFiles.add(clean.toLowerCase());
                files.push(clean);
            }
        }

        // 8. Bảng tài chính tóm tắt (nếu có BCDKT)
        let financialTableSummary = "";
        const bcdktMatch = text.indexOf("Chi tiết dữ liệu báo cáo");
        if (bcdktMatch !== -1) {
            financialTableSummary = text.substring(bcdktMatch, bcdktMatch + 2000).trim();
        }

        return {
            category,
            mdn,
            companyName,
            title,
            formFields,
            trichYeu,
            files,
            financialTableSummary,
            rawTextSample: text.substring(0, 1500)
        };
    }""")


def build_markdown_content(detail: Dict[str, Any], row_info: Dict[str, Any]) -> str:
    """Đóng gói dữ liệu báo cáo thành Markdown chi tiết, chuyên nghiệp."""
    mck = row_info.get("mck") or "UBCKNN"
    san = row_info.get("san") or "N/A"
    don_vi = detail.get("companyName") or row_info.get("don_vi") or "Doanh nghiệp"
    mdn = detail.get("mdn") or "N/A"
    title = detail.get("title") or row_info.get("title") or "Báo cáo công bố thông tin"
    category = detail.get("category") or "Công bố thông tin"
    thoi_gian_gui = row_info.get("thoi_gian_gui") or "N/A"
    trich_yeu = detail.get("trichYeu") or row_info.get("trich_yeu_table") or "Không có trích yếu tóm tắt."
    files = detail.get("files") or []
    fields = detail.get("formFields") or {}

    md = []
    md.append(f"# [{mck}] {title}\n")
    md.append(f"> **Cơ quan giám sát:** Ủy ban Chứng khoán Nhà nước (UBCKNN)")
    md.append(f"> **Chuyên mục:** {category} | **Sàn giao dịch:** {san} | **Thời gian gửi:** {thoi_gian_gui}\n")

    md.append("## 1. Thông tin doanh nghiệp công bố")
    md.append(f"- **Tên đơn vị:** {don_vi}")
    md.append(f"- **Mã chứng khoán:** `{mck}`")
    md.append(f"- **Mã số doanh nghiệp (MDN):** `{mdn}`")
    md.append(f"- **Sàn niêm yết:** {san}\n")

    md.append("## 2. Chi tiết nội dung văn bản báo cáo")
    md.append(f"**Trích yếu nội dung:**")
    md.append(f"```text\n{trich_yeu}\n```\n")

    if fields:
        md.append("### Các chỉ tiêu & thông tin hành chính")
        md.append("| Chỉ tiêu / Thuộc tính | Giá trị ghi nhận |")
        md.append("| :--- | :--- |")
        for k, v in fields.items():
            if v and str(v).strip():
                md.append(f"| {k} | **{v}** |")
        md.append("")

    if files:
        md.append("## 3. Danh mục tài liệu & Văn bản đính kèm")
        md.append("Các văn bản, báo cáo tài chính và nghị quyết có chữ ký số gốc được nộp về UBCKNN:")
        for idx, f in enumerate(files, 1):
            md.append(f"{idx}. 📄 `{f}` *(Văn bản xác thực ký số điện tử)*")
        md.append("")

    fin = detail.get("financialTableSummary")
    if fin:
        md.append("## 4. Bảng số liệu báo cáo tài chính chi tiết (Trích lục)")
        md.append("```text")
        md.append(fin[:1500])
        md.append("```\n")

    md.append("---\n*Nguồn dữ liệu: Cổng thông tin điện tử UBCKNN (https://congbothongtin.ssc.gov.vn)*")
    return "\n".join(md)


def build_html_content(detail: Dict[str, Any], row_info: Dict[str, Any]) -> str:
    """Tạo HTML tương ứng để hiển thị đẹp mắt trong Modal trên website."""
    mck = row_info.get("mck") or "UBCKNN"
    san = row_info.get("san") or "N/A"
    don_vi = detail.get("companyName") or row_info.get("don_vi") or "Doanh nghiệp"
    mdn = detail.get("mdn") or "N/A"
    title = detail.get("title") or row_info.get("title") or "Báo cáo công bố thông tin"
    category = detail.get("category") or "Công bố thông tin"
    thoi_gian_gui = row_info.get("thoi_gian_gui") or "N/A"
    trich_yeu = detail.get("trichYeu") or row_info.get("trich_yeu_table") or "Không có trích yếu tóm tắt."
    files = detail.get("files") or []
    fields = detail.get("formFields") or {}

    html_parts = [
        '<div class="ssc-report-detail" style="font-family: inherit; line-height: 1.6;">',
        '  <div style="background: rgba(16, 185, 129, 0.08); border-left: 4px solid #10b981; padding: 12px 16px; margin-bottom: 20px; border-radius: 4px;">',
        f'    <div style="font-size: 0.85rem; color: #10b981; font-weight: 600; text-transform: uppercase;">UBCKNN • {category}</div>',
        f'    <div style="font-size: 1.15rem; font-weight: 700; color: var(--text-primary, #1e293b); margin: 4px 0;">[{mck}] {title}</div>',
        f'    <div style="font-size: 0.85rem; color: var(--text-secondary, #64748b);">Doanh nghiệp: <b>{don_vi}</b> | MDN: <code>{mdn}</code> | Sàn: <b>{san}</b> | Ngày gửi: <b>{thoi_gian_gui}</b></div>',
        '  </div>',
        '  <h3 style="font-size: 1.05rem; font-weight: 600; border-bottom: 1px solid var(--border, #e2e8f0); padding-bottom: 6px; margin-top: 20px;">Nội dung trích yếu</h3>',
        f'  <div style="background: var(--bg-secondary, #f8fafc); border: 1px solid var(--border, #e2e8f0); padding: 14px; border-radius: 6px; font-size: 0.95rem; white-space: pre-wrap; margin-bottom: 20px;">{trich_yeu}</div>',
    ]

    if fields:
        html_parts.append('  <h3 style="font-size: 1.05rem; font-weight: 600; border-bottom: 1px solid var(--border, #e2e8f0); padding-bottom: 6px;">Thông tin hành chính & chỉ tiêu</h3>')
        html_parts.append('  <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.9rem;">')
        for k, v in fields.items():
            if v and str(v).strip():
                html_parts.append(f'    <tr style="border-bottom: 1px solid var(--border, #e2e8f0);"><td style="padding: 8px 12px; color: var(--text-secondary, #64748b); width: 35%; font-weight: 500;">{k}</td><td style="padding: 8px 12px; font-weight: 600; color: var(--text-primary, #1e293b);">{v}</td></tr>')
        html_parts.append('  </table>')

    if files:
        html_parts.append('  <h3 style="font-size: 1.05rem; font-weight: 600; border-bottom: 1px solid var(--border, #e2e8f0); padding-bottom: 6px;">Văn bản & File đính kèm</h3>')
        html_parts.append('  <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px;">')
        for f in files:
            html_parts.append(f'    <div style="display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--bg-secondary, #f8fafc); border: 1px solid var(--border, #e2e8f0); border-radius: 6px;"><span style="font-size: 1.2rem;">📄</span><span style="font-family: monospace; font-size: 0.9rem; word-break: break-all; flex: 1;">{f}</span><span style="font-size: 0.75rem; background: #e0f2fe; color: #0284c7; padding: 2px 8px; border-radius: 4px; font-weight: 600;">PDF KÝ SỐ</span></div>')
        html_parts.append('  </div>')

    fin = detail.get("financialTableSummary")
    if fin:
        html_parts.append('  <h3 style="font-size: 1.05rem; font-weight: 600; border-bottom: 1px solid var(--border, #e2e8f0); padding-bottom: 6px;">Trích lục dữ liệu báo cáo tài chính</h3>')
        html_parts.append(f'  <pre style="background: var(--bg-secondary, #f8fafc); border: 1px solid var(--border, #e2e8f0); padding: 12px; border-radius: 6px; font-size: 0.82rem; overflow-x: auto; max-height: 250px;">{fin[:1500]}</pre>')

    html_parts.append('  <div style="margin-top: 24px; padding-top: 12px; border-top: 1px dashed var(--border, #e2e8f0); font-size: 0.8rem; color: var(--text-secondary, #64748b); text-align: right;">Cổng công bố thông tin Ủy ban Chứng khoán Nhà nước (UBCKNN)</div>')
    html_parts.append('</div>')

    return "\n".join(html_parts)


async def crawl_ssc(limit: int = 15, headless: bool = True) -> int:
    """Thực thi quy trình crawl báo cáo UBCKNN."""
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:crawl4ai_password_2026@postgres:5432/news_db")
    saved_count = 0

    log.info(f"Khởi động trình thu thập SSC UBCKNN (limit={limit})...")

    async with Database(dsn) as db:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--ignore-certificate-errors",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ignore_https_errors=True,
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()

            try:
                log.info(f"1. Điều hướng tới {SSC_SEARCH_URL}...")
                await page.goto(SSC_SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3500)

                # Lấy danh sách hàng ngoài bảng
                rows = await extract_table_rows(page)
                log.info(f"Đã phát hiện {len(rows)} báo cáo trên bảng dữ liệu SSC.")

                if not rows:
                    log.warning("Không tìm thấy hàng nào trong bảng SSC!")
                    return 0

                crawl_targets = rows[:limit]

                for item in crawl_targets:
                    idx = item["index"]
                    mck = item["mck"] or "UBCKNN"
                    raw_title = item["title"] or f"Báo cáo công bố {idx + 1}"
                    log.info(f"[{idx + 1}/{len(crawl_targets)}] Bắt đầu lấy nội dung chi tiết: [{mck}] {raw_title[:60]}...")

                    try:
                        # Click vào link của báo cáo
                        link_locator = page.locator("a[id*='cl1']").nth(idx)
                        if await link_locator.count() == 0:
                            log.warning(f"Không tìm thấy link tại index {idx}, bỏ qua.")
                            continue

                        await link_locator.click()
                        await page.wait_for_timeout(3500)

                        # Bóc tách trang chi tiết
                        detail = await extract_report_detail(page)

                        # Chuẩn bị dữ liệu bài viết
                        company = detail.get("companyName") or item.get("don_vi") or "Doanh nghiệp"
                        final_title = detail.get("title") or raw_title
                        if mck and not final_title.startswith(f"[{mck}]"):
                            full_title = f"[{mck}] {final_title} - {company}"
                        else:
                            full_title = f"{final_title} - {company}"

                        category = detail.get("category") or "Công bố thông tin"
                        san = item.get("san") or ""
                        mdn = detail.get("mdn") or ""
                        thoi_gian_str = item.get("thoi_gian_gui") or detail.get("formFields", {}).get("Ngày ký ban hành") or ""
                        pub_date = parse_vn_date(thoi_gian_str) or datetime.now()

                        # URL định danh duy nhất cho bản ghi
                        # VD: https://congbothongtin.ssc.gov.vn/#report-CTD-20261003-0301447257-idx0
                        date_slug = pub_date.strftime("%Y%m%d")
                        unique_url = f"{SSC_BASE_URL}/#report-{mck}-{date_slug}-{mdn or '0'}-r{idx}"

                        sapo_cand = (detail.get("trichYeu") or "").strip()
                        if not sapo_cand or "*" in sapo_cand or "Required" in sapo_cand or len(sapo_cand) < 6:
                            sapo_cand = (item.get("trich_yeu_table") or "").strip()
                        if not sapo_cand:
                            sapo_cand = f"Báo cáo công bố thông tin {final_title} của {company} ({mck}) nộp tới Ủy ban Chứng khoán Nhà nước vào ngày {thoi_gian_str}."
                        sapo = sapo_cand
                        markdown_content = build_markdown_content(detail, item)
                        html_content = build_html_content(detail, item)

                        tags = [t for t in [mck, san, "UBCKNN", "Công bố thông tin", category] if t]

                        article_data = {
                            "source": "ssc",
                            "external_id": f"ssc-{mck}-{date_slug}-{idx}",
                            "url": unique_url,
                            "canonical_url": unique_url,
                            "category": category,
                            "title": full_title[:300],
                            "sapo": sapo[:1000],
                            "author": company[:200],
                            "original_source": "Ủy ban Chứng khoán Nhà nước (UBCKNN)",
                            "published_at": pub_date,
                            "thumbnail_url": None,
                            "tags": tags,
                            "content_text": markdown_content,
                            "content_markdown": markdown_content,
                            "content_html": html_content,
                            "word_count": len(markdown_content.split()),
                            "listing_url": SSC_SEARCH_URL,
                            "listing_section": category,
                            "http_status": 200,
                        }

                        # Lưu vào DB
                        art_id, is_new = await db.upsert_article(article_data)
                        status_str = "Tạo mới" if is_new else "Cập nhật"
                        log.info(f" -> Thành công: {status_str} bài ID={art_id} [{mck}] ({len(detail.get('files', []))} files đính kèm)")
                        saved_count += 1

                    except Exception as err:
                        log.error(f"Lỗi khi cào báo cáo index {idx}: {err}", exc_info=False)

                    finally:
                        # Điều hướng trở lại danh sách để nạp trang mới an toàn
                        try:
                            await page.goto(SSC_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                            await page.wait_for_timeout(3000)
                        except Exception as reload_err:
                            log.warning(f"Lỗi khi reload danh sách: {reload_err}")

            finally:
                await browser.close()

    log.info(f"Hoàn thành thu thập SSC: đã lưu {saved_count} báo cáo vào cơ sở dữ liệu.")
    return saved_count


def main():
    parser = argparse.ArgumentParser(description="SSC UBCKNN Report Crawler")
    parser.add_argument("--limit", type=int, default=10, help="Số lượng báo cáo cần lấy (mặc định 10)")
    parser.add_argument("--no-headless", action="store_true", help="Chạy có giao diện")
    args = parser.parse_args()

    asyncio.run(crawl_ssc(limit=args.limit, headless=not args.no_headless))


if __name__ == "__main__":
    main()
