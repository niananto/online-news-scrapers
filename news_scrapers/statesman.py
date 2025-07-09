from __future__ import annotations
"""StatesmanScraper – keyword search + article hydration for *The Statesman*.

Key points
~~~~~~~~~~
* **Search URL**: ``https://www.thestatesman.com/page/<page>?s=<keyword>`` – exactly
  **17** *real* article tiles per page (hard‑limit).
* **Article pages** embed a *NewsArticle* JSON‑LD block.  It often contains the
  **sub‑heading only** in *articleBody*, so we promote that to *summary* and
  scrape the full body from the DOM.
* Fully compatible with the new :class:`news_scrapers.base.BaseNewsScraper` v2
  – same public interface and error handling.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import html
import json
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup  # type: ignore – BeautifulSoup4

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind

logger = logging.getLogger(__name__)

# ──────────────────────────── constants / helpers ───────────────────────────
_MAX_PER_PAGE = 17  # hard‑wired by *thestatesman.com* template
_TZ_IST = timezone(timedelta(hours=5, minutes=30))  # UTC+05:30
_DATE_PATTERNS = (
    "%d %B, %Y",
    "%d %B, %Y %I:%M %p",
    "%d %b, %Y",
    "%d %b, %Y %I:%M %p",
)


def _to_iso(date_str: str | None) -> Optional[str]:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in _DATE_PATTERNS:
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=_TZ_IST)
            return dt.isoformat()
        except Exception:
            continue
    return None


def _section_from_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    path = urlparse(url).path.lstrip("/")
    return path.split("/", 1)[0] if path else None


# ───────────────────────────────── scraper class ────────────────────────────
class StatesmanScraper(BaseNewsScraper):
    """Scraper for **The Statesman** search results & articles."""

    REQUEST_METHOD: str = "GET"
    RESPONSE_KIND: ResponseKind = ResponseKind.HTML  # listings are HTML pages

    BASE_URL: str = "https://www.thestatesman.com/"  # overridden per‑call

    HEADERS: Dict[str, str] = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"  # noqa: E501
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    # ───────────────────────────── public: search ───────────────────────────
    def search(
        self,
        keyword: str,
        page: int = 1,
        size: int = 30,
        **kwargs: Any,
    ) -> List[Article]:
        """Return *≤ 17* hydrated articles for the given *keyword* & *page*."""

        if size > _MAX_PER_PAGE:
            logger.warning(
                "The Statesman returns max %d results per page – truncating from %d",
                _MAX_PER_PAGE,
                size,
            )
            size = _MAX_PER_PAGE

        original_base = self.BASE_URL  # remember for restore
        self.BASE_URL = f"https://www.thestatesman.com/page/{page}"
        self.PARAMS = {"s": keyword}
        self.PAYLOAD = {}

        try:
            articles = super().search(keyword, page, size, **kwargs)
        finally:
            self.BASE_URL = original_base
        return articles[:size]

    # ───────────────────── listing parser + hydration ───────────────────────
    def _parse_response(self, html_text: str):  # type: ignore[override]
        soup = BeautifulSoup(html_text, "lxml")
        cards = soup.select("div.loop-grid-3 article")[: _MAX_PER_PAGE]

        out: List[Article] = []
        for card in cards:
            art = Article(outlet="The Statesman")

            # title + url
            if (h4 := card.select_one("h4.post-title")) and (a := h4.find("a")):
                art.title = a.get_text(strip=True)
                art.url = a.get("href")

            # teaser / summary (listing excerpt)
            if (p := card.select_one("p.excerpt")):
                art.summary = p.get_text(" ", strip=True)

            # hero image
            if (img := card.select_one("figure img")):
                src = img.get("data-src") or img.get("src")
                if src:
                    art.media.append(MediaItem(url=src, caption=img.get("alt"), type="image"))

            # author + date (tiny gray line under title)
            if (span := card.select_one("span.author-name")):
                art.author = span.get_text(strip=True)
            if (span := card.select_one("span.mr-10")):
                art.published_at = _to_iso(span.get_text(strip=True))

            # section from URL
            art.section = _section_from_url(art.url)

            # ── hydration ──
            if art.url:
                try:
                    detail = self._fetch_article_details(art.url)
                except Exception:  # pragma: no cover
                    logger.exception("hydrate failed for %s", art.url)
                    detail = {}

                art.author = detail.get("author") or art.author
                art.content = detail.get("content") or art.content
                art.summary = detail.get("summary") or art.summary
                art.tags = detail.get("tags", art.tags)
                art.published_at = detail.get("published_at") or art.published_at

                extras: List[MediaItem] = detail.get("media", [])
                art.media.extend(m for m in extras if m.url not in {mi.url for mi in art.media})

            out.append(art)
        return out

    # ───────────────────────── article hydration ───────────────────────────
    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        detail: Dict[str, Any] = {
            "author": None,
            "summary": None,
            "content": None,
            "tags": [],
            "published_at": None,
            "media": [],
        }

        # 1) JSON‑LD – may hold *articleBody* (usually sub‑heading)
        ld = self._extract_from_jsonld(soup)
        if ld:
            detail.update(ld)

        # 2) DOM fall‑backs
        self._fallback_dom_parse(soup, detail)
        return detail

    # ────────────────────────── JSON‑LD helpers ────────────────────────────
    @staticmethod
    def _extract_from_jsonld(soup: BeautifulSoup) -> Dict[str, Any] | None:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or ""
            try:
                data = json.loads(html.unescape(raw))
            except json.JSONDecodeError:
                continue

            queue: List[Any] = [data]
            while queue:
                node = queue.pop()
                if isinstance(node, dict):
                    if node.get("@type") == "NewsArticle":
                        return StatesmanScraper._parse_ldjson_article(node)
                    queue.extend(node.values())
                elif isinstance(node, list):
                    queue.extend(node)
        return None

    @staticmethod
    def _parse_ldjson_article(node: Dict[str, Any]) -> Dict[str, Any]:
        # author(s)
        author_field = node.get("author") or []
        if isinstance(author_field, dict):
            author_field = [author_field]
        author = ", ".join(a.get("name") for a in author_field if isinstance(a, dict)) or None

        # images
        media: List[MediaItem] = []
        match node.get("image"):
            case str(url):
                media.append(MediaItem(url=url, caption=None, type="image"))
            case list(lst):
                media.extend(MediaItem(url=u, caption=None, type="image") for u in lst if u)
            case dict(d):
                if (u := d.get("url")):
                    media.append(MediaItem(url=u, caption=None, type="image"))

        # description (Yoast sub‑heading)
        summary = node.get("description") or None

        # articleBody – VERY often identical to *description*; treat cautiously
        body = node.get("articleBody") or None
        if body and summary and body.strip() == summary.strip():
            body = None  # will scrape full body from DOM later

        return {
            "author": author,
            "summary": summary,
            "content": body,
            "tags": StatesmanScraper._split_keywords(node.get("keywords")),
            "published_at": node.get("datePublished") or node.get("dateModified"),
            "media": media,
        }

    # helper: split **keywords** field which can be comma or pipe separated
    @staticmethod
    def _split_keywords(val: Any) -> List[str]:
        out: List[str] = []
        if not val:
            return out
        if isinstance(val, str):
            out = [t.strip() for t in re.split(r",|\|", val) if t.strip()]
        elif isinstance(val, list):
            out = [str(t).strip() for t in val if str(t).strip()]
        return out

    # ───────────────────────── DOM fall‑backs ──────────────────────────────
    @staticmethod
    def _fallback_dom_parse(soup: BeautifulSoup, out: Dict[str, Any]) -> None:
        # author
        if not out.get("author"):
            if (a := soup.select_one(".author_name, .byline, [itemprop='author']")):
                out["author"] = a.get_text(" ", strip=True)

        # summary – meta description (preferred) or first <p>
        if not out.get("summary"):
            meta = soup.find("meta", property="og:description") or soup.find(
                "meta", attrs={"name": "description"}
            )
            if meta and meta.get("content"):
                out["summary"] = meta["content"].strip()

        # content – all <p>/<li>/<h2> inside article body
        if not out.get("content"):
            body_sel = soup.select_one(
                "article.entry-wraper, .entry-main-content, [itemprop='articleBody']"
            )
            if body_sel:
                # drop non‑content nodes
                for tag in body_sel.find_all(["script", "style", "noscript", "ins", "iframe"]):
                    tag.decompose()
                paras = [
                    t.get_text(" ", strip=True)
                    for t in body_sel.find_all(["p", "li", "h2"]) or [body_sel]
                ]
                text = "\n".join(p for p in paras if p)
                out["content"] = re.sub(r"\n{2,}", "\n", text).strip() or None

        # remove duplicate summary at the start of content
        if out.get("content") and out.get("summary"):
            content = out["content"].lstrip()
            summary = out["summary"].strip()
            if content.startswith(summary):
                out["content"] = content[len(summary) :].lstrip(" \n")

        # tags
        if not out.get("tags"):
            tag_links = soup.select(".tags li a, a[rel~=tag], .topic-tags a")
            out["tags"] = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        # inline hero image
        if not out.get("media"):
            if (img := soup.select_one("article img")) and img.get("src"):
                out["media"] = [MediaItem(url=img["src"], caption=img.get("alt"), type="image")]


# ───────────────────────────── smoke test ─────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual run only
    logging.basicConfig(level=logging.INFO)
    sc = StatesmanScraper()
    arts = sc.search("bangladesh", page=1, size=25)
    for a in arts:
        print(f"{a.published_at} – {a.title}\n{a.url}\nSummary: {a.summary}\nBody ≈ {len(a.content or '')} chars\nTags: {a.tags}\n")
    print(f"Total {len(arts)} articles (max {_MAX_PER_PAGE})")
