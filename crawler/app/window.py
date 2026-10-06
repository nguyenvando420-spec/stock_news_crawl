"""Khoảng ngày cần crawl (theo ngày đăng bài): hôm nay cho job định kỳ, hoặc ngày/khoảng ngày cho chạy tay."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo


def local_tz() -> tzinfo:
    """Múi giờ dùng để hiểu 'ngày' (mặc định giờ Việt Nam)."""
    return ZoneInfo(os.getenv("CRAWL_TZ") or os.getenv("TZ") or "Asia/Ho_Chi_Minh")


@dataclass(frozen=True)
class DateWindow:
    start: datetime          # bao gồm
    end: datetime            # không bao gồm
    first_day: date
    last_day: date

    def contains(self, dt: Optional[datetime]) -> bool:
        return dt is not None and self.start <= dt < self.end

    def is_newer(self, dt: Optional[datetime]) -> bool:
        return dt is not None and dt >= self.end

    def is_older(self, dt: Optional[datetime]) -> bool:
        return dt is not None and dt < self.start

    def __str__(self) -> str:
        days = f"{self.first_day}" if self.first_day == self.last_day else f"{self.first_day} → {self.last_day}"
        return f"{days} [{self.start:%d/%m %H:%M} – {self.end:%d/%m %H:%M} {self.start:%z}]"


def days_window(first: date, last: date, tz: Optional[tzinfo] = None) -> DateWindow:
    tz = tz or local_tz()
    if last < first:
        raise ValueError(f"Ngày kết thúc {last} nhỏ hơn ngày bắt đầu {first}")
    start = datetime.combine(first, time.min, tz)
    end = datetime.combine(last + timedelta(days=1), time.min, tz)
    return DateWindow(start=start, end=end, first_day=first, last_day=last)


def today_window(lookback: timedelta = timedelta(0), tz: Optional[tzinfo] = None) -> DateWindow:
    """Bài đăng trong ngày hôm nay.

    `lookback`: khi chạy định kỳ, lần chạy đầu tiên sau nửa đêm vẫn lấy nốt các bài đăng sát nửa đêm hôm
    trước mà chu kỳ trước chưa kịp thấy (start = min(00:00 hôm nay, now - lookback)).
    """
    tz = tz or local_tz()
    now = datetime.now(tz)
    w = days_window(now.date(), now.date(), tz)
    if lookback and now - lookback < w.start:
        w = DateWindow(start=now - lookback, end=w.end, first_day=(now - lookback).date(), last_day=w.last_day)
    return w
