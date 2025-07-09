from __future__ import annotations

"""EconomicTimesScraper – topic search + article hydration for **The Economic Times**.

This module follows the exact conventions of the other scrapers that inherit
from :class:`news_scrapers.base.BaseNewsScraper` (v2):

*   **Search endpoint** – ``https://economictimes.indiatimes.com/lazyload_topicmore.cms``
    returns *raw HTML* fragments identical to the JS‑generated infinite scroll
    cards on the site’s *topic* pages.
*   **Parameters**:
    ``query=<keyword>&type=article&curpg=<page>&pageno=<page>``.  We map our
    1‑based *page* argument onto both *curpg* and *pageno*.
*   The fragment contains ``div.topicstry`` blocks.  Each card is parsed into a
    thin :class:`~news_scrapers.base.Article` (title, url, hero‑img, summary,
    IST timestamp, section).
*   Every result is then **hydrated** with the full article page, giving us
    author, full body, tags and richer media via:

    1.  Embedded *NewsArticle* JSON‑LD (preferred).
    2.  Best‑effort DOM selectors (fallback).

The implementation mirrors the style of the existing HTML‑oriented scrapers
(e.g. *IndiaDotComScraper*, *StatesmanScraper*).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
import html
import json
import logging
import re

from bs4 import BeautifulSoup  # type: ignore – BeautifulSoup4
import requests

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind

logger = logging.getLogger(__name__)

# ───────────────────────────── helpers / constants ──────────────────────────
_TZ_IST = timezone(timedelta(hours=5, minutes=30))

_DATE_RE = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<mon>[A-Za-z]{3})[,\s]+(?P<year>\d{4}),?\s+"
    r"(?P<hour>\d{1,2})[.:](?P<minute>\d{2})\s*(?P<ampm>[AP]M)",
    re.I,
)

_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

_PLACEHOLDER_IMG = re.compile(r"^(?:data:|https?:.*blank\.gif)", re.I)


def _to_iso_ist(text: str | None) -> str | None:
    """Convert *09 Jul, 2025, 09.26 PM IST* → ISO‑8601 (IST)."""
    if not text:
        return None
    text = text.replace("IST", "").strip()
    m = _DATE_RE.search(text)
    if not m:
        return None
    day = int(m.group("day"))
    month = _MONTHS.get(m.group("mon").title()[:3])
    year = int(m.group("year"))
    hour = int(m.group("hour"))
    minute = int(m.group("minute"))
    ampm = m.group("ampm").upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    try:
        return (
            datetime(year, month, day, hour, minute, tzinfo=_TZ_IST)
            .isoformat(timespec="seconds")
        )
    except Exception:
        return None


def _section_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path.lstrip("/")
    parts = path.split("/", 2)
    if parts and parts[0] in (
        "industry",
        "news",
        "markets",
        "markets/stocks",
        "opinion",
    ):
        return parts[0]
    return None


# ───────────────────────────── scraper class ────────────────────────────────
class EconomicTimesScraper(BaseNewsScraper):
    """Scraper for **The Economic Times** topic listings & articles."""

    REQUEST_METHOD: str = "GET"
    RESPONSE_KIND: ResponseKind = ResponseKind.HTML  # listings are raw HTML

    BASE_URL: str = "https://economictimes.indiatimes.com/lazyload_topicmore.cms"

    HEADERS: Dict[str, str] = {
        "accept": "text/html, */*; q=0.01",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "x-requested-with": "XMLHttpRequest",
    }

    # ───────────────────────────── public: search ──────────────────────────
    def search(
        self,
        keyword: str,
        page: int = 1,
        size: int = 30,
        **kwargs: Any,
    ) -> List[Article]:
        """Return up to *size* hydrated articles for *keyword* & *page*."""
        # The endpoint ignores *size* – every page returns ≈ 20 articles.
        if size > 20:
            logger.warning("The Statesman returns max 20 results per page – truncating from %s", size)
            size = 20

        self.PARAMS = {
            "query": keyword,
            "type": "article",
            "curpg": str(page),
            "pageno": str(page),
        }
        self.PAYLOAD = {}
        arts = super().search(keyword, page, size, **kwargs)
        return arts[:size]

    # ───────────────────── listing parser + hydration ──────────────────────
    def _parse_response(self, html_text: str):  # type: ignore[override]
        soup = BeautifulSoup(html_text, "lxml")
        cards = soup.select("div.topicstry")

        out: List[Article] = []
        for card in cards:
            art = Article(outlet="Economic Times")

            # title + url
            a = card.select_one("div.contentD a[title]")
            if a:
                art.title = a.get("title") or a.get_text(strip=True)
                art.url = a.get("href")

            # summary
            if (wrap := card.select_one("div.wrapLines")):
                art.summary = wrap.get_text(" ", strip=True)

            # hero image
            if (img := card.select_one("div.imgD img")):
                src = img.get("data-src") or img.get("src")
                if src and not _PLACEHOLDER_IMG.search(src):
                    art.media.append(
                        MediaItem(url=src, caption=img.get("alt"), type="image")
                    )

            # published_at
            if (tm := card.select_one("time")):
                art.published_at = _to_iso_ist(tm.get_text(strip=True))

            # section from URL
            art.section = _section_from_url(art.url)

            # ── hydrate ──
            if art.url:
                try:
                    detail = self._fetch_article_details(art.url)
                except Exception:  # pragma: no cover
                    logger.exception("hydrate failed for %s", art.url)
                    detail = {}

                art.author = detail.get("author") or art.author
                art.content = detail.get("content") or art.content
                art.tags = detail.get("tags", art.tags)
                art.published_at = detail.get("published_at") or art.published_at

                extra_media: List[MediaItem] = detail.get("media", [])
                art.media.extend(
                    m for m in extra_media if m.url not in {mi.url for mi in art.media}
                )

            out.append(art)
        return out

    # ───────────────────────── article hydration ──────────────────────────
    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        detail: Dict[str, Any] = {
            "author": None,
            "content": None,
            "tags": [],
            "published_at": None,
            "media": [],
        }

        ld = self._find_newsarticle_ldjson(soup)
        if ld:
            detail.update(ld)
        else:
            self._fallback_dom_parse(soup, detail)
        return detail

    # ───────────────────── JSON‑LD helpers (copy‑paste pattern) ────────────
    @staticmethod
    def _find_newsarticle_ldjson(soup: BeautifulSoup) -> Dict[str, Any] | None:
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
                        return EconomicTimesScraper._extract_from_jsonld(node)
                    queue.extend(node.values())
                elif isinstance(node, list):
                    queue.extend(node)
        return None

    @staticmethod
    def _extract_from_jsonld(node: Dict[str, Any]) -> Dict[str, Any]:
        # Author(s)
        author_field = node.get("author") or []
        if isinstance(author_field, dict):
            author_field = [author_field]
        author = ", ".join(a.get("name") for a in author_field if isinstance(a, dict) and a.get("name")) or None

        # Images
        imgs: List[str] = []
        match node.get("image"):
            case str(u):
                imgs.append(u)
            case list(lst):
                imgs.extend(lst)
            case dict(d):
                if (u := d.get("url")):
                    imgs.append(u)
        media_items = [MediaItem(url=u, caption=None, type="image") for u in imgs if u]

        # Tags
        tags: List[str] = []
        if (kw := node.get("keywords")):
            if isinstance(kw, str):
                tags = [t.strip() for t in re.split(r",|\|", kw) if t.strip()]
            elif isinstance(kw, list):
                tags = [str(t).strip() for t in kw if str(t).strip()]

        return {
            "author": author,
            "content": node.get("articleBody"),
            "tags": tags,
            "published_at": node.get("datePublished") or node.get("dateModified"),
            "media": media_items,
        }

    # ───────────────────── DOM fallback selectors ────────────────────────
    @staticmethod
    def _fallback_dom_parse(soup: BeautifulSoup, out: Dict[str, Any]) -> None:
        # Author
        if not out.get("author"):
            if (el := soup.select_one(".byline span, .byline, [itemprop='author']")):
                out["author"] = el.get_text(strip=True)

        # Content
        if not out.get("content"):
            body = soup.select_one(
                "[itemprop='articleBody'], #artText, .ga-headlines, article"
            )
            if body:
                for tag in body.find_all(["script", "style", "noscript", "figure", "aside"]):
                    tag.decompose()
                paragraphs = body.find_all(["p", "h2", "li"]) or [body]
                text = "\n".join(p.get_text(" ", strip=True) for p in paragraphs)
                out["content"] = re.sub(r"\n{2,}", "\n", text).strip()

        # Tags
        if not out.get("tags"):
            tag_links = soup.select(
                ".tags li a, a[rel~=tag], .article_tags a, .clearfix a[href*='/tag/']"
            )
            out["tags"] = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        # Images (fallback – first image in article body)
        if not out.get("media"):
            img = soup.select_one("article img, #artText img, .ga-headlines img")
            if img and (src := img.get("src")) and not _PLACEHOLDER_IMG.search(src):
                out["media"] = [MediaItem(url=src, caption=img.get("alt"), type="image")]


# ─────────────────────────────── demo ─────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    sc = EconomicTimesScraper()
    arts = sc.search("bangladesh", page=1, size=10)
    for a in arts:
        print(f"{a.published_at} – {a.title}\n{a.url}\n{a.summary}\n")