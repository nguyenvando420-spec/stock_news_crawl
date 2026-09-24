import re
from typing import Dict, Any, Optional
from parsel import Selector
from lxml import html as lxml_html

try:
    import html2text
except ImportError:
    html2text = None


DEFAULT_NOISE_TAGS = {
    "script", "style", "noscript", "nav", "header", "footer",
    "aside", "iframe", "form", "svg", "button", "input"
}

DEFAULT_NOISE_SELECTORS = [
    ".ads", ".ad", ".ad-banner", ".advertisement", "[class*='banner']", "[id*='banner']",
    "[class*='sidebar']", "[id*='sidebar']", ".relate-container", ".related-news",
    ".list-news-related", "[class*='relate']", "[class*='box-category']",
    ".social-share", ".share-buttons", "[class*='social']", "[class*='sharing']", "[class*='shares']",
    ".comments", ".comment", ".tags", ".bottom-info", ".btn_chiase", ".social-pin",
    "[class*='newsletter']", ".link-content-footer", ".box-tuyendung", "[class*='recommend']",
    "[class*='widget']", ".tindnd", ".kbw-social", ".right-detail", ".rightdetail",
    "[class*='top-index']", "[class*='ticker']", "[class*='breadcrumb']",
    "[class*='op-player']", "[class*='audio-player']", "[class*='voice']", "audio", "video",
    "a[href^='javascript:']", "a[href*='javascript:void']",
    "img[src*='delivery']", "img[src*='bannerid']", "img[src*='pixel']", "img[src*='tracking']",
    "#am-widget", "[id*='am-widget']", "[class*='am-widget']",
    ".carousel-container", "[class*='carousel-container']",
    ".more-on-this-topic-wrapper", "[class*='more-on-this-topic']",
    "[class*='print:hidden']", "[class*='affiliate']", "[class*='commerce']",
    "[id*='outbrain']", "[id*='taboola']", "[class*='outbrain']", "[class*='taboola']",
    "a[href*='skimresources.com']"
]

FALLBACK_CONTENT_SELECTORS = [
    ".article__body",
    ".cms-body",
    ".zce-content-body",
    "div[class*='article_WYSIWYG']",
    "#article",
    "[data-test='article-body']",
    "article.fck_detail",
    "article#articleContent",
    ".e-magazine__body",
    "article.e-magazine",
    "div.article-content",
    ".detail-content.afcbc-body",
    ".contentdetail",
    ".detail__content",
    ".detail-content",
    ".details__content",
    "[itemprop='articleBody']",
    ".article-content",
    ".article-body",
    ".entry-content",
    ".post-content",
    ".story-body",
    "#channel-detail",
    "#content_detail",
    "#entry-body",
    "#maincontent",
    ".maincontent",
    "#main-content",
    "article[class*='detail']",
    "article.article-content",
    "article.entry-content",
    "article.content",
    "article[class*='main']",
    "article",
    "main",
]


def clean_text(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    cleaned = re.sub(r"\s+", " ", str(val)).strip()
    return cleaned if cleaned else None


def clean_title(title: Optional[str]) -> Optional[str]:
    title = clean_text(title)
    if not title:
        return None
    # Remove common site suffixes like " - Báo VnExpress", " | CafeF.vn", " - CNBC"
    cleaned = re.sub(
        r"\s*[-|–]\s*(Báo\s+)?(VnExpress|CafeF|VnEconomy|Vietstock|Báo Đầu tư|Dân trí|Tuổi Trẻ|Thanh Niên|VietnamPlus|VTV|VietNamNet|Nhân Dân|CNBC|Bloomberg|Reuters|MarketWatch|Financial Times|BBC).*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return cleaned.strip() or title


def clean_description(desc: Optional[str]) -> Optional[str]:
    if not desc:
        return None
    # Strip HTML tags like <img>, <a>, <p> if accidentally captured in description
    desc = re.sub(r"<[^>]+>", " ", str(desc))
    return clean_text(desc)


def html_to_clean_markdown(cleaned_html_str: str) -> str:
    if html2text is not None:
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.body_width = 0
        h.ignore_emphasis = False
        h.protect_links = True
        h.single_line_break = False
        md = h.handle(cleaned_html_str).strip()
        # Clean excessive newlines
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md

    # Fallback without html2text
    try:
        tree = lxml_html.fromstring(cleaned_html_str)
        lines = []
        for el in tree.iterchildren():
            tag = el.tag.lower()
            text = clean_text(el.text_content())
            if not text:
                continue
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                lines.append(f"{'#' * level} {text}")
            elif tag == "p":
                lines.append(text)
            elif tag in ("ul", "ol"):
                for li in el.cssselect("li"):
                    li_txt = clean_text(li.text_content())
                    if li_txt:
                        lines.append(f"- {li_txt}")
            elif tag == "blockquote":
                lines.append(f"> {text}")
            else:
                lines.append(text)
        return "\n\n".join(lines)
    except Exception:
        return clean_text(cleaned_html_str) or ""


CLOUDFLARE_TITLE_PATTERNS = [
    r"just a moment\.{2,}",
    r"attention required!?",
    r"security check",
    r"please wait\.{2,}",
    r"checking your browser",
    r"verify you are human",
    r"ddos-guard",
    r"cloudflare",
    r"automated access to our sites must comply",
    r"access denied",
    r"robot or human",
    r"pardon our interruption",
]

CLOUDFLARE_BODY_PATTERNS = [
    r"/cdn-cgi/challenge-platform/",
    r"_cf_chl_opt",
    r"__cf_chl_tk",
    r"cf-browser-verification",
    r"cf-turnstile",
    r"challenges\.cloudflare\.com",
    r"enable javascript and cookies to continue",
    r"checking your browser before accessing",
    r"ray id:",
    r"automated access to our sites must comply",
    r"perimeterx",
]


def is_cloudflare_challenge(html_content: str, title: Optional[str] = None) -> bool:
    """
    Detects if the returned HTML is a Cloudflare / anti-bot challenge interstitial
    rather than genuine article content.
    """
    if not html_content:
        return False

    if title:
        low_title = title.strip().lower()
        for pat in CLOUDFLARE_TITLE_PATTERNS:
            if re.search(pat, low_title):
                return True

    snippet = html_content[:20000].lower()
    for pat in CLOUDFLARE_BODY_PATTERNS:
        if re.search(pat, snippet):
            return True

    return False


def extract_article_data(html_content: str, cfg: Dict[str, Any], seed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses HTML content using configured selectors (or smart fallbacks)
    and returns cleaned title, description, author, canonical_url,
    content_html, and content_markdown.
    """
    if not html_content or not html_content.strip():
        return {
            "title": seed.get("title"),
            "description": seed.get("description"),
            "author": seed.get("author"),
            "canonical_url": seed.get("url"),
            "content_markdown": None,
            "content_html": None,
        }

    sel = Selector(text=html_content)

    # Cloudflare / anti-bot detection: Never overwrite real title/desc with challenge page
    raw_title = sel.css("title::text").get() or ""
    if is_cloudflare_challenge(html_content, raw_title):
        return {
            "title": seed.get("title"),
            "description": clean_description(seed.get("description")),
            "author": seed.get("author"),
            "canonical_url": seed.get("url"),
            "content_markdown": None,
            "content_html": None,
            "is_blocked": True,
            "block_reason": "Cloudflare challenge page detected",
        }

    selectors = cfg.get("selectors") or {}

    # 1. Title
    title = None
    cfg_title_sel = selectors.get("title")
    if cfg_title_sel:
        for single_sel in [s.strip() for s in cfg_title_sel.split(",") if s.strip()]:
            if "::attr(" in single_sel:
                title = sel.css(single_sel).get()
            elif "::text" in single_sel:
                parts = sel.css(single_sel).getall()
                title = " ".join(p.strip() for p in parts if p.strip())
            else:
                nodes = sel.css(single_sel)
                if nodes:
                    parts = nodes[0].css("*::text, ::text").getall()
                    title = " ".join(p.strip() for p in parts if p.strip())
            if title and len(title.strip()) > 3:
                break
    if not title:
        for fb_sel in [
            'meta[property="og:title"]::attr(content)',
            'meta[name="twitter:title"]::attr(content)',
            'h1.title::text',
            'h1.title-detail::text',
            'h1.headline::text',
            'h1.article-title::text',
            'h1.article__title::text',
            'h1::text',
            'title::text',
        ]:
            title = sel.css(fb_sel).get()
            if title and title.strip():
                break
    title = clean_title(title) or seed.get("title")

    # 2. Description
    description = None
    cfg_desc_sel = selectors.get("description")
    if cfg_desc_sel:
        for single_sel in [s.strip() for s in cfg_desc_sel.split(",") if s.strip()]:
            if "::attr(" in single_sel:
                description = sel.css(single_sel).get()
            elif "::text" in single_sel:
                parts = sel.css(single_sel).getall()
                description = " ".join(p.strip() for p in parts if p.strip())
            else:
                nodes = sel.css(single_sel)
                if nodes:
                    parts = nodes[0].css("*::text, ::text").getall()
                    description = " ".join(p.strip() for p in parts if p.strip())
            if description and len(description.strip()) > 10:
                break
    if not description:
        for fb_sel in [
            'meta[property="og:description"]::attr(content)',
            'meta[name="description"]::attr(content)',
            '.article__sapo',
            '.cms-desc',
            '.sapo',
            'p.description',
            '.article-sapo',
            '.detail__summary',
            'p.sapo',
        ]:
            if "::attr(" in fb_sel:
                description = sel.css(fb_sel).get()
            else:
                nodes = sel.css(fb_sel)
                if nodes:
                    parts = nodes[0].css("*::text, ::text").getall()
                    description = " ".join(p.strip() for p in parts if p.strip())
            if description and len(description.strip()) > 10:
                break
    description = clean_description(description) or clean_description(seed.get("description"))

    # 3. Author
    author = None
    cfg_author_sel = selectors.get("author")
    if cfg_author_sel:
        author = sel.css(cfg_author_sel).get()
    if not author:
        for fb_sel in [
            'meta[name="author"]::attr(content)',
            'meta[property="article:author"]::attr(content)',
            '[rel="author"]::text',
            '.author::text',
            'p.author::text',
            'p.Normal strong::text',
        ]:
            author = sel.css(fb_sel).get()
            if author and author.strip():
                break
    author = clean_text(author) or seed.get("author")

    # 4. Canonical URL
    canonical_url = sel.css('link[rel="canonical"]::attr(href)').get()
    canonical_url = clean_text(canonical_url) or seed.get("canonical_url") or seed.get("url")

    # 5. Clean Article Content
    content_markdown = None
    content_html = None

    try:
        tree = lxml_html.fromstring(html_content)

        # Find target content element
        content_node = None
        custom_content_sel = selectors.get("content")
        if custom_content_sel:
            pure_sel = re.sub(r"::[\w-]+(\([^\)]*\))?", "", custom_content_sel).strip()
            for single_sel in [s.strip() for s in pure_sel.split(",") if s.strip()]:
                found = tree.cssselect(single_sel)
                best_match = None
                best_len = 0
                for el in found:
                    t = clean_text(el.text_content()) or ""
                    if len(t) > best_len:
                        best_len = len(t)
                        best_match = el
                if best_match is not None and best_len > 40:
                    content_node = best_match
                    break

        if content_node is None:
            best_node = None
            best_len = 0
            for cand in FALLBACK_CONTENT_SELECTORS:
                found = tree.cssselect(cand)
                for el in found:
                    t = clean_text(el.text_content()) or ""
                    if len(t) > best_len:
                        best_len = len(t)
                        best_node = el
                if best_len > 250:
                    content_node = best_node
                    break
            if content_node is None and best_node is not None and best_len > 40:
                content_node = best_node

        if content_node is None:
            # Last resort: body or entire document
            found = tree.cssselect("body")
            content_node = found[0] if found else tree

        # Remove noise elements inside the content node
        # 1. Custom noise selector
        custom_remove_sel = selectors.get("remove")
        if custom_remove_sel:
            pure_remove_sel = re.sub(r"::[\w-]+(\([^\)]*\))?", "", custom_remove_sel).strip()
            for bad_el in content_node.cssselect(pure_remove_sel):
                try:
                    bad_el.getparent().remove(bad_el)
                except Exception:
                    pass

        # 2. Standard noise selectors
        for bad_sel in DEFAULT_NOISE_SELECTORS:
            for bad_el in content_node.cssselect(bad_sel):
                try:
                    bad_el.getparent().remove(bad_el)
                except Exception:
                    pass

        # 3. Noise tags
        for tag in DEFAULT_NOISE_TAGS:
            for bad_el in content_node.iter(tag):
                try:
                    bad_el.getparent().remove(bad_el)
                except Exception:
                    pass

        # 4. Remove common trailing clusters (See more on, More on this topic)
        for el in content_node.xpath('.//*[contains(text(), "See more on") or contains(text(), "More on this topic")]'):
            curr = el
            while curr is not None and curr != content_node:
                cls_name = curr.get("class") or ""
                if "article-page-grid" in cls_name or "more-on-this-topic" in cls_name or "storyline" in cls_name:
                    try:
                        curr.getparent().remove(curr)
                    except Exception:
                        pass
                    break
                curr = curr.getparent()

        # Convert to string and clean Markdown
        cleaned_html = lxml_html.tostring(content_node, encoding="utf-8").decode("utf-8")
        content_html = cleaned_html
        content_markdown = html_to_clean_markdown(cleaned_html)

    except Exception:
        # Fallback to parsel text extraction if lxml parsing failed
        text_nodes = sel.css("article p::text, main p::text, p::text").getall()
        content_markdown = "\n\n".join(x.strip() for x in text_nodes if x.strip())
        content_html = html_content

    return {
        "title": title,
        "description": description,
        "author": author,
        "canonical_url": canonical_url,
        "content_markdown": content_markdown,
        "content_html": content_html,
    }
