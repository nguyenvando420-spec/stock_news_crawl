"""Nạp config/sites.yaml -> SiteConfig, và biên dịch selector sang schema của Crawl4AI.

Toàn bộ kiến thức riêng của từng website nằm trong YAML; file này chỉ chứa logic CHUNG.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml

_HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = Path(os.getenv("SITES_CONFIG", "")) if os.getenv("SITES_CONFIG") else next(
    (p for p in (_HERE.parent / "config" / "sites.yaml", _HERE.parent.parent / "config" / "sites.yaml") if p.exists()),
    _HERE.parent / "config" / "sites.yaml",
)

_ATTR_RE = re.compile(r"^[\w:-]+$")

# Thời gian tương đối hay gặp ở trang listing: "8 phút trước", "1h trước", "3 hours ago"...
_REL_RE = re.compile(
    r"(\d+)\s*(giây|phút|p|giờ|h|ngày|tuần|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\s*(trước|ago)",
    re.I,
)
_REL_UNITS = {
    "giây": "seconds", "second": "seconds", "sec": "seconds",
    "phút": "minutes", "p": "minutes", "minute": "minutes", "min": "minutes",
    "giờ": "hours", "h": "hours", "hour": "hours", "hr": "hours",
    "ngày": "days", "day": "days",
    "tuần": "weeks", "week": "weeks",
}
_YESTERDAY_RE = re.compile(r"(hôm qua|yesterday)\D*(\d{1,2})[:h](\d{2})", re.I)


# ---------------------------------------------------------------------------
# Selector mini-language:  "css"  |  "css@attr"  |  "@attr"  |  [ ...ưu tiên... ]
# ---------------------------------------------------------------------------
def _as_list(spec: Any) -> list[str]:
    if spec is None:
        return []
    return [s for s in (spec if isinstance(spec, list) else [spec]) if s]


def _split(candidate: str) -> tuple[str, Optional[str]]:
    sel, sep, attr = candidate.rpartition("@")
    if sep and _ATTR_RE.match(attr):
        return sel.strip(), attr
    return candidate.strip(), None


def compile_field(name: str, spec: Any) -> list[dict]:
    """1 field có nhiều ứng viên -> nhiều field JsonCss tên `name__0`, `name__1`, ..."""
    fields = []
    for i, cand in enumerate(_as_list(spec)):
        sel, attr = _split(cand)
        f: dict[str, Any] = {"name": f"{name}__{i}"}
        if sel:
            f["selector"] = sel
        f.update({"type": "attribute", "attribute": attr} if attr else {"type": "text"})
        fields.append(f)
    return fields


def compile_tags(name: str, spec: Any) -> list[dict]:
    """tags: không @ -> list text của mọi phần tử; có @ -> 1 chuỗi, tách dấu phẩy sau."""
    fields = []
    for i, cand in enumerate(_as_list(spec)):
        sel, attr = _split(cand)
        if attr:
            fields.append({"name": f"{name}__{i}", "selector": sel, "type": "attribute", "attribute": attr})
        else:
            fields.append({"name": f"{name}__{i}", "selector": sel, "type": "list",
                           "fields": [{"name": "v", "type": "text"}]})
    return fields


def _candidates(row: dict, name: str) -> list[Any]:
    """Giá trị của name__0, name__1... theo thứ tự (JsonCss bỏ qua key có giá trị None)."""
    keys = []
    for k in row:
        base, sep, idx = k.rpartition("__")
        if sep and base == name and idx.isdigit():
            keys.append((int(idx), k))
    return [row[k] for _, k in sorted(keys)]


def coalesce(row: dict, name: str) -> Any:
    """Lấy giá trị đầu tiên khác rỗng trong name__0, name__1, ..."""
    for v in _candidates(row, name):
        if isinstance(v, str):
            v = re.sub(r"\s+", " ", v).strip()
        if v:
            return v
    return None


def coalesce_tags(row: dict, name: str = "tags") -> list[str]:
    for v in _candidates(row, name):
        if isinstance(v, list):
            tags = [re.sub(r"\s+", " ", x.get("v", "")).strip(" ,;") for x in v if isinstance(x, dict)]
        elif isinstance(v, str):
            tags = [t.strip() for t in re.split(r"[,;]", v)]
        else:
            tags = []
        tags = [t for t in tags if t]
        if tags:
            return list(dict.fromkeys(tags))
    return []


# ---------------------------------------------------------------------------
# SiteConfig
# ---------------------------------------------------------------------------
ARTICLE_FIELDS = ("title", "sapo", "author", "published_at", "category", "canonical_url",
                  "thumbnail_url", "original_source")


@dataclass
class SiteConfig:
    key: str
    name: str
    base_url: str
    listing_urls: list[str]
    article_url_regex: re.Pattern
    blocks: dict[str, str]
    item_fields: dict[str, Any]
    content_selector: str
    exclude: list[str]
    site_fields: dict[str, Any]
    default_fields: dict[str, Any]
    pagination: dict[str, Any] = field(default_factory=dict)
    browser: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    timezone: str = "+07:00"
    date_formats: list[str] = field(default_factory=list)
    min_words: int = 50
    listing_wait_for: Optional[str] = None
    article_wait_for: Optional[str] = None

    # ---------- Crawl4AI schemas ----------
    def listing_schema(self) -> dict:
        item = []
        for fname, spec in self.item_fields.items():
            item += compile_field(fname, spec)
        return {
            "name": f"{self.key} listing",
            "baseSelector": "html",
            "fields": [{"name": block, "selector": sel, "type": "list", "fields": item}
                       for block, sel in self.blocks.items()],
        }

    def article_schema(self) -> dict:
        fields = []
        for prefix, src in (("site", self.site_fields), ("default", self.default_fields)):
            for fname, spec in src.items():
                compiled = compile_tags if fname == "tags" else compile_field
                fields += compiled(f"{prefix}.{fname}", spec)
        return {"name": f"{self.key} article", "baseSelector": "html", "fields": fields}

    @property
    def all_items_selector(self) -> str:
        return ", ".join(self.blocks.values())

    # ---------- URL helpers ----------
    def normalize_url(self, href: Optional[str]) -> Optional[str]:
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            return None
        parts = urlsplit(urljoin(self.base_url + "/", href.strip()))
        clean = urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))
        return clean if self.article_url_regex.match(clean) else None

    def matches(self, url: str) -> bool:
        host = urlsplit(url).netloc.lower().removeprefix("www.")
        return host == urlsplit(self.base_url).netloc.lower().removeprefix("www.")

    def page_url(self, listing_url: str, page1_html: str, page: int) -> Optional[str]:
        tpl = self.pagination.get("url")
        if not tpl:
            return None
        url_no_ext = re.sub(r"\.html?$", "", listing_url.rstrip("/"))
        values = {
            "page": page,
            "listing_url": listing_url.rstrip("/"),
            "url_no_ext": url_no_ext,
        }
        for var, pattern in (self.pagination.get("vars") or {}).items():
            m = re.search(pattern, page1_html or "")
            if not m:
                return None
            values[var] = m.group(1)
        return tpl.format(**values)

    # ---------- parsing ----------
    @property
    def tz(self) -> tzinfo:
        return datetime.strptime(self.timezone, "%z").tzinfo

    def parse_datetime(self, value: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
        """ISO-8601 | date_formats trong YAML | tương đối ("8 phút trước") | thiếu năm ("05/10 20:30")."""
        if not value:
            return None
        value = re.sub(r"\s+", " ", str(value)).strip()
        now = now or datetime.now(self.tz)
        low = value.lower()

        if low in ("vừa xong", "just now"):
            return now
        if (m := _REL_RE.search(low)):
            unit = m.group(2).lower()
            unit = _REL_UNITS.get(unit) or _REL_UNITS.get(unit.rstrip("s"), "minutes")
            return now - timedelta(**{unit: int(m.group(1))})
        if (m := _YESTERDAY_RE.search(low)):
            return (now - timedelta(days=1)).replace(hour=int(m.group(2)), minute=int(m.group(3)),
                                                      second=0, microsecond=0)

        dt = None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in self.date_formats:
                try:
                    dt = datetime.strptime(value, fmt)
                except ValueError:
                    continue
                if "%Y" not in fmt and "%y" not in fmt:
                    # "05/10 20:30" -> năm hiện tại; nếu thành ra ở tương lai thì là năm trước
                    dt = dt.replace(year=now.year)
                    if dt > now.replace(tzinfo=None) + timedelta(days=1):
                        dt = dt.replace(year=now.year - 1)
                break
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)
        return dt


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_sites(path: Path | str = DEFAULT_CONFIG) -> dict[str, SiteConfig]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    sites: dict[str, SiteConfig] = {}
    for key, cfg in (raw.get("sites") or {}).items():
        cfg = cfg or {}
        listing = cfg.get("listing", {})
        article = cfg.get("article", {})
        d_listing = defaults.get("listing", {})
        d_article = defaults.get("article", {})
        content = article.get("content") or "article"
        if not listing.get("blocks"):
            raise ValueError(f"[{key}] thiếu listing.blocks trong {path}")
        sites[key] = SiteConfig(
            key=key,
            name=cfg.get("name", key),
            base_url=cfg["base_url"].rstrip("/"),
            listing_urls=cfg.get("listing_urls", []),
            article_url_regex=re.compile(cfg["article_url_pattern"]),
            blocks=dict(listing["blocks"]),
            item_fields={**d_listing.get("item", {}), **listing.get("item", {})},
            content_selector=content,
            exclude=list(d_article.get("exclude", [])) + list(article.get("exclude", [])),
            site_fields=article.get("fields", {}),
            default_fields=d_article.get("fields", {}),
            pagination=cfg.get("pagination") or {},
            browser=_deep_merge(defaults.get("browser", {}), cfg.get("browser", {})),
            enabled=cfg.get("enabled", defaults.get("enabled", True)),
            timezone=cfg.get("timezone", defaults.get("timezone", "+07:00")),
            date_formats=cfg.get("date_formats", []) + defaults.get("date_formats", []),
            min_words=cfg.get("min_words", defaults.get("min_words", 50)),
            listing_wait_for=listing.get("wait_for") or f"css:{', '.join(listing['blocks'].values())}",
            article_wait_for=article.get("wait_for") or f"css:{content}",
        )
    return sites


def site_for_url(sites: dict[str, SiteConfig], url: str) -> SiteConfig:
    for s in sites.values():
        if s.matches(url):
            return s
    raise ValueError(f"Chưa có cấu hình cho {urlsplit(url).netloc} trong {DEFAULT_CONFIG}")
