"""CLI: python -m app [options]

Ví dụ:
  python -m app --list-sites                      # liệt kê site trong config/sites.yaml
  python -m app                                   # crawl MỌI site đang enabled (trang 1, không lọc ngày)
  python -m app --site cafef --site vietstock     # chỉ vài site
  python -m app --url https://cafef.vn/doanh-nghiep.chn   # URL chuyên mục bất kỳ của site đã cấu hình
  python -m app --site tinnhanhchungkhoan --pages 3       # thêm trang 2,3 (url / click "Xem thêm")
  python -m app --dry-run                         # chỉ in danh sách link, không crawl bài
  python -m app --force                           # crawl lại cả bài đã có trong DB

Theo ngày đăng bài (tự phân trang cho tới khi qua mốc ngày, tối đa --max-pages trang):
  python -m app --today --interval-minutes 10     # JOB ĐỊNH KỲ: chỉ bài đăng hôm nay, lặp mỗi 10 phút
  python -m app --date 2026-10-01                 # LỊCH SỬ (chạy tay): bài đăng ngày 01/10/2026
  python -m app --from 2026-09-25 --to 2026-09-30 # LỊCH SỬ: khoảng ngày (bao gồm 2 đầu)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from contextlib import aclosing
from datetime import date, datetime, timedelta
from typing import Optional

from crawl4ai import AsyncWebCrawler

from .crawl import CrawlStats, ListingItem, build_crawler, crawl_articles, discover_links, iter_listing_pages
from .db import Database
from .site_config import DEFAULT_CONFIG, SiteConfig, load_sites, site_for_url
from .window import DateWindow, days_window, local_tz, today_window

log = logging.getLogger("app")

# URL đã crawl nhưng ngày đăng nằm ngoài khoảng cần lấy (không lưu DB).
# Nhớ trong tiến trình để job định kỳ không crawl lại chúng ở mỗi chu kỳ.
_OUT_OF_WINDOW: dict[str, Optional[datetime]] = {}


def _csv(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _date(value: str) -> date:
    for parse in (date.fromisoformat, lambda v: datetime.strptime(v, "%d/%m/%Y").date()):
        try:
            return parse(value)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Ngày không hợp lệ: {value!r} (dùng YYYY-MM-DD hoặc DD/MM/YYYY)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env = os.environ.get
    p = argparse.ArgumentParser(prog="python -m app", description="Crawl tin tức bằng Crawl4AI -> PostgreSQL")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="Đường dẫn sites.yaml")
    p.add_argument("--site", action="append", dest="sites", default=None,
                   help="Key site trong sites.yaml (lặp lại được). Mặc định: mọi site enabled")
    p.add_argument("--url", action="append", dest="urls", default=None,
                   help="URL trang chuyên mục (lặp lại được), domain phải có trong sites.yaml")
    p.add_argument("--list-sites", action="store_true", help="Liệt kê site trong config rồi thoát")

    d = p.add_argument_group("Lọc theo ngày đăng (tự phân trang tới khi qua mốc ngày)")
    g = d.add_mutually_exclusive_group()
    g.add_argument("--today", action="store_true", help="Chỉ bài đăng hôm nay (dùng cho job định kỳ)")
    g.add_argument("--date", type=_date, help="Chỉ bài đăng ngày này (YYYY-MM-DD) - chạy tay dữ liệu lịch sử")
    g.add_argument("--from", dest="date_from", type=_date, help="Từ ngày (YYYY-MM-DD), dùng kèm --to")
    d.add_argument("--to", dest="date_to", type=_date, help="Đến ngày, bao gồm (mặc định: hôm nay)")
    d.add_argument("--max-pages", type=int, default=int(env("CRAWL_MAX_PAGES", "50")),
                   help="Giới hạn an toàn số trang listing mỗi chuyên mục khi lọc theo ngày")

    p.add_argument("--pages", type=int, default=int(env("CRAWL_PAGES", "1")),
                   help="Số trang listing khi KHÔNG lọc theo ngày (trang 2+ theo pagination trong config)")
    p.add_argument("--max-articles", type=int, default=int(env("CRAWL_MAX_ARTICLES", "30")),
                   help="Khi KHÔNG lọc theo ngày: tối đa số bài MỚI mỗi trang chuyên mục mỗi lần chạy (0 = không giới hạn)")
    p.add_argument("--concurrency", type=int, default=int(env("CRAWL_CONCURRENCY", "3")),
                   help="Số tab trình duyệt chạy song song")
    p.add_argument("--blocks", default=env("CRAWL_BLOCKS", ""),
                   help="Chỉ lấy các khối này (vd: featured,stream). Mặc định: tất cả khối trong config")
    p.add_argument("--min-words", type=int, default=None, help="Ghi đè min_words của config")
    p.add_argument("--force", action="store_true", help="Crawl lại cả những bài đã có trong DB")
    p.add_argument("--dry-run", action="store_true", help="Chỉ lấy & in danh sách link, không crawl bài, không ghi DB")
    p.add_argument("--interval-minutes", type=float, default=float(env("CRAWL_INTERVAL_MINUTES", "0")),
                   help="> 0: chạy lặp lại mỗi N phút (tính từ lúc bắt đầu mỗi lần chạy)")
    p.add_argument("--headful", action="store_true", help="Mở trình duyệt có giao diện (debug local)")
    p.add_argument("--database-url", default=env("DATABASE_URL"), help="Chuỗi kết nối PostgreSQL")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    args.sites = args.sites or _csv(env("CRAWL_SITES"))
    args.urls = args.urls or _csv(env("CRAWL_URLS"))
    args.blocks = set(_csv(args.blocks)) or None
    if not (args.dry_run or args.list_sites) and not args.database_url:
        p.error("Thiếu --database-url hoặc biến môi trường DATABASE_URL")
    if args.date_to and not args.date_from:
        p.error("--to phải dùng kèm --from")
    if (args.date or args.date_from) and args.interval_minutes > 0:
        p.error("--date/--from là chạy tay 1 lần cho dữ liệu lịch sử; job định kỳ dùng --today")
    return args


def build_window(args) -> Optional[DateWindow]:
    """Tính lại ở MỖI lần chạy (job định kỳ qua nửa đêm sẽ tự chuyển sang ngày mới)."""
    if args.today:
        # Lần chạy đầu sau nửa đêm vẫn lấy nốt bài đăng sát nửa đêm mà chu kỳ trước chưa thấy
        lookback = timedelta(minutes=2 * args.interval_minutes) if args.interval_minutes > 0 else timedelta(0)
        return today_window(lookback=lookback)
    if args.date:
        return days_window(args.date, args.date)
    if args.date_from:
        return days_window(args.date_from, args.date_to or datetime.now(local_tz()).date())
    return None


def resolve_targets(args, sites: dict[str, SiteConfig]) -> dict[str, list[str]]:
    """-> {site_key: [listing_url, ...]}"""
    targets: dict[str, list[str]] = {}
    for url in args.urls:
        targets.setdefault(site_for_url(sites, url).key, []).append(url)
    for key in args.sites:
        if key not in sites:
            raise SystemExit(f"Không có site '{key}' trong config. Có: {', '.join(sites)}")
        targets.setdefault(key, []).extend(sites[key].listing_urls)
    if not targets:  # mặc định: mọi site enabled
        targets = {k: s.listing_urls for k, s in sites.items() if s.enabled}
    return targets


def _fmt(dt: Optional[datetime]) -> str:
    return dt.astimezone(local_tz()).strftime("%d/%m/%Y %H:%M") if dt else "?"


def _page_oldest(items: list[ListingItem]) -> Optional[datetime]:
    """Ngày của bài CUỐI trang có ngày (listing sắp xếp mới -> cũ, nên đó là bài cũ nhất của trang)."""
    return next((it.published_at for it in reversed(items) if it.published_at), None)


# ---------------------------------------------------------------------------
# Bước 3 + 4: crawl từng bài và lưu DB
# ---------------------------------------------------------------------------
async def crawl_and_save(crawler: AsyncWebCrawler, db: Database, site: SiteConfig, items: list[ListingItem],
                         args, stats: CrawlStats, window: Optional[DateWindow]) -> None:
    async for item, article, error in crawl_articles(
        crawler, site, items, concurrency=args.concurrency, min_words=args.min_words
    ):
        if error:
            stats.failed += 1
            stats.errors.append({"url": item.url, "error": error[:500]})
            log.warning("✗ %s -> %s", item.url, error[:200])
            continue
        item.published_at = article["published_at"] or item.published_at
        if window and not window.contains(article["published_at"]):
            stats.skipped += 1
            _OUT_OF_WINDOW[item.url] = article["published_at"]
            log.info("↷ [%s] bỏ qua, đăng %s ngoài khoảng ngày: %s", site.key, _fmt(article["published_at"]),
                     article["title"][:70])
            continue
        article_id, inserted = await db.upsert_article(article)
        stats.saved += 1
        log.info("✓ [%s] #%s %s [%s, %d từ] %s", site.key, article_id, "NEW" if inserted else "UPD",
                 _fmt(article["published_at"]), article["word_count"], article["title"][:70])


async def _dry_run(crawler, site, listing_url, args, window, stats) -> None:
    items = await discover_links(crawler, site, listing_url, pages=args.pages, blocks=args.blocks)
    stats.links_found = len(items)
    for i, it in enumerate(items, 1):
        mark = "" if window is None else (
            "? " if it.published_at is None else "✓ " if window.contains(it.published_at) else "✗ ")
        print(f"{i:3d}. {mark}{_fmt(it.published_at):16s} [{it.section:8s}] {it.title[:100]}\n     {it.url}")


async def _run_latest(crawler, db, site, listing_url, args, stats) -> None:
    """Không lọc ngày: `--pages` trang đầu, bỏ link đã có, tối đa `--max-articles` bài."""
    items = await discover_links(crawler, site, listing_url, pages=args.pages, blocks=args.blocks)
    stats.links_found = len(items)
    if not args.force:
        existing = await db.existing_urls(it.url for it in items)
        items = [it for it in items if it.url not in existing]
    if args.max_articles > 0:
        items = items[: args.max_articles]
    stats.links_new = len(items)
    log.info("[%s] %d link tìm thấy, %d bài cần crawl", site.key, stats.links_found, stats.links_new)
    await crawl_and_save(crawler, db, site, items, args, stats, None)


async def _run_window(crawler, db, site, listing_url, args, stats, window: DateWindow) -> None:
    """Lọc theo ngày đăng, đi lần lượt từng trang listing (mới -> cũ):

    - Ngày của mỗi link lấy từ: listing (nếu config có `published_at`) > DB (bài đã lưu) > bộ nhớ tạm.
    - Link biết ngày & ngoài khoảng -> bỏ, không crawl.
    - Trang có bài cuối chưa rõ ngày -> crawl bài đó trước để biết trang đang ở mốc nào;
      nếu cả trang còn MỚI hơn khoảng cần lấy (chạy lịch sử) thì bỏ qua cả trang, sang trang sau.
    - Bài cũ nhất của trang đã CŨ hơn ngày bắt đầu -> dừng phân trang.
    """
    page = 0
    stopped = False
    async with aclosing(iter_listing_pages(crawler, site, listing_url, max_pages=args.max_pages,
                                           blocks=args.blocks)) as pages:
        async for page, _page_url, items in pages:
            stats.links_found += len(items)
            in_db = await db.published_dates(it.url for it in items)
            for it in items:
                if it.url in in_db:
                    it.published_at = in_db[it.url] or it.published_at
                elif it.url in _OUT_OF_WINDOW:
                    it.published_at = _OUT_OF_WINDOW[it.url] or it.published_at

            def wanted(it: ListingItem) -> bool:
                if not args.force and (it.url in in_db or it.url in _OUT_OF_WINDOW):
                    return False
                return it.published_at is None or window.contains(it.published_at)

            pending = [it for it in items if wanted(it)]

            last = items[-1]
            if last.published_at is None and last in pending:
                pending.remove(last)
                stats.links_new += 1
                await crawl_and_save(crawler, db, site, [last], args, stats, window)
            if window.is_newer(_page_oldest(items)):
                # bài cuối trang vẫn mới hơn khoảng cần lấy -> các bài chưa rõ ngày trên trang cũng vậy
                pending = [it for it in pending if it.published_at is not None]

            stats.links_new += len(pending)
            log.info("[%s] trang %d: %d link, %d bài cần crawl", site.key, page, len(items), len(pending))
            await crawl_and_save(crawler, db, site, pending, args, stats, window)

            oldest = _page_oldest(items)
            if window.is_older(oldest):
                log.info("[%s] trang %d đã tới bài đăng %s (trước %s), dừng phân trang",
                         site.key, page, _fmt(oldest), window.first_day)
                stopped = True
                break
    if not stopped and page >= args.max_pages > 1:
        log.warning("[%s] đã tới --max-pages=%d mà chưa qua mốc %s - có thể còn thiếu bài, tăng --max-pages",
                    site.key, args.max_pages, window.first_day)


async def run_listing(crawler: AsyncWebCrawler, db: Database | None, site: SiteConfig,
                      listing_url: str, args, window: Optional[DateWindow]) -> CrawlStats:
    stats = CrawlStats()
    run_id = await db.start_run(site.key, listing_url, window and window.first_day,
                                window and window.last_day) if db else None
    status = "failed"
    try:
        if args.dry_run:
            await _dry_run(crawler, site, listing_url, args, window, stats)
        elif window is None:
            await _run_latest(crawler, db, site, listing_url, args, stats)
        else:
            await _run_window(crawler, db, site, listing_url, args, stats, window)
        status = "success" if stats.failed == 0 else ("partial" if stats.saved else "failed")
        return stats
    except Exception as exc:
        stats.errors.append({"url": listing_url, "error": repr(exc)[:500]})
        log.exception("Lỗi khi xử lý %s", listing_url)
        return stats
    finally:
        if db and run_id is not None:
            await db.finish_run(run_id, status=status, links_found=stats.links_found,
                                links_new=stats.links_new, saved=stats.saved,
                                failed=stats.failed, errors=stats.errors, skipped=stats.skipped)


async def run_once(args) -> int:
    started = time.perf_counter()
    sites = load_sites(args.config)
    targets = resolve_targets(args, sites)
    window = build_window(args)
    log.info("Khoảng ngày đăng: %s", window or "không lọc (trang mới nhất)")
    summary: list[tuple[str, CrawlStats]] = []

    db = Database(args.database_url) if not args.dry_run else None
    if db:
        await db.__aenter__()
    try:
        for key, urls in targets.items():
            site = sites[key]
            # 1 trình duyệt cho mỗi site (cấu hình browser có thể khác nhau giữa các site)
            try:
                async with build_crawler(site, headless=not args.headful) as crawler:
                    for url in urls:
                        summary.append((url, await run_listing(crawler, db, site, url, args, window)))
            except Exception:  # noqa: BLE001 - 1 site lỗi không làm dừng các site khác
                log.exception("[%s] lỗi khởi tạo/crawl site", key)
                summary.append((key, CrawlStats(errors=[{"error": "site crashed"}])))
    finally:
        if db:
            await db.__aexit__(None, None, None)

    log.info("=" * 70)
    for url, s in summary:
        log.info("found=%-3d new=%-3d saved=%-3d skipped=%-3d failed=%-3d %s",
                 s.links_found, s.links_new, s.saved, s.skipped, s.failed, url)
    log.info("Hoàn tất sau %.1fs", time.perf_counter() - started)
    return 0 if all(s.links_found for _, s in summary) else 1


async def main_async(args) -> int:
    if args.interval_minutes <= 0:
        return await run_once(args)
    period = args.interval_minutes * 60
    while True:
        started = time.monotonic()
        try:
            await run_once(args)
        except Exception:  # noqa: BLE001 - vòng lặp không được chết vì 1 lần lỗi
            log.exception("Lần chạy lỗi, sẽ thử lại ở chu kỳ sau")
        # chu kỳ tính từ lúc BẮT ĐẦU lần chạy (fixed-rate), trừ đi thời gian đã crawl
        wait = max(0.0, period - (time.monotonic() - started))
        log.info("Lần chạy kế tiếp sau %.1f phút (chu kỳ %.1f phút)", wait / 60, args.interval_minutes)
        await asyncio.sleep(wait)


def list_sites(args) -> None:
    for key, s in load_sites(args.config).items():
        flag = "ON " if s.enabled else "OFF"
        print(f"[{flag}] {key:20s} {s.name:24s} blocks={','.join(s.blocks)} "
              f"pagination={s.pagination.get('type', '-')}")
        for u in s.listing_urls:
            print(f"        {u}")


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    for noisy in ("httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.list_sites:
        list_sites(args)
        return
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
