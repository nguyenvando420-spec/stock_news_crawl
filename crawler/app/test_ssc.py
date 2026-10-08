import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/home/appuser/.cache/ms-playwright/chromium-1208/chrome-linux/chrome",
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ignore_https_errors=True
        )
        page = await context.new_page()
        print("1. Truy cập SSC...")
        await page.goto("https://congbothongtin.ssc.gov.vn/faces/NewsSearch", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        # Lấy danh sách link dòng 1
        link1 = page.locator("a[id*='cl1']").first
        report_title_in_table = (await link1.inner_text()).strip()
        print(f"2. Bấm vào link báo cáo: {report_title_in_table}")
        
        await link1.click()
        await page.wait_for_timeout(4000)
        
        print(f"3. URL sau click: {page.url}")
        
        # Bóc tách các trường dữ liệu trên trang chi tiết
        body_text = await page.inner_text("body")
        print("\n--- NỘI DUNG BODY TRANG BÁO CÁO (30 DÒNG ĐẦU TIÊN) ---")
        lines = [line.strip() for line in body_text.split("\n") if line.strip()]
        for l in lines[:35]:
            print("  |", l)
            
        # Thử lấy các trường form cụ thể
        inputs = await page.eval_on_selector_all("input, textarea", """
            els => els.map(e => ({
                id: e.id,
                name: e.name,
                tag: e.tagName,
                value: e.value,
                placeholder: e.placeholder
            }))
        """)
        print("\n--- CÁC INPUT / TEXTAREA CÓ GIÁ TRỊ ---")
        for inp in inputs:
            if inp.get("value"):
                tag = inp.get("tag")
                iid = inp.get("id")
                val = inp.get("value")
                print(f"  [{tag}] id={iid}: {val}")
                
        # Thử tìm các file đính kèm
        attachments = await page.eval_on_selector_all("a", """
            els => els.map(e => ({
                id: e.id,
                text: e.innerText.trim(),
                href: e.href
            })).filter(e => e.text.endsWith(".pdf") || e.text.endsWith(".doc") || e.text.endsWith(".docx") || e.text.endsWith(".zip") || e.id.includes("cxl1"))
        """)
        print("\n--- FILE ĐÍNH KÈM ---")
        for att in attachments:
            print("  File:", att)

        # Kiểm tra nút Quay lại
        back_btns = await page.eval_on_selector_all("a, button, img", """
            els => els.map(e => ({
                tag: e.tagName,
                id: e.id,
                title: e.title,
                alt: e.alt,
                src: e.src || "",
                text: e.innerText.trim()
            })).filter(e => (e.title && e.title.includes("Quay")) || (e.alt && e.alt.includes("Quay")) || e.id.includes("cb1") || (e.src && e.src.includes("back")))
        """)
        print("\n--- NÚT QUAY LẠI ---")
        for b in back_btns:
            print("  Back btn:", b)

        # Thử bấm nút quay lại xem có về lại bảng không
        if back_btns:
            print(f"\n4. Thử bấm nút quay lại: id={back_btns[0]['id']}...")
            await page.locator(f"#{back_btns[0]['id'].replace(':', r'\:')}").click()
            await page.wait_for_timeout(3000)
            print("  URL sau khi bấm quay lại:", page.url)
            has_table = await page.locator("a[id*='cl1']").count()
            print(f"  Số link báo cáo trên bảng sau quay lại: {has_table}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
