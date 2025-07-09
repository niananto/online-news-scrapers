from __future__ import annotations

"""DailyPioneerScraper – keyword search + article hydration for *The Daily Pioneer*.

Fixes requested by Nazmul
─────────────────────────
* **Author** – always pick the first non‑empty chunk **after** the date in
  the little grey *newsInfo* bar, so we get values like “Press Trust of India”
  or “Pioneer News Service”.
* **Section** – derive from the URL path segment right after the year
  (e.g. ``/2025/world/...`` → ``world``) and back‑fill from the breadcrumb on
  the article page if still missing.
* **Media** – richer extraction pipeline:
  1. ``og:image`` <meta>; 2. *NewsArticle* JSON‑LD ``image``; 3. first inline
     ``<img>`` in the story body; 4. figure/thumbnail on the listing card.
  Skips obvious placeholders like ``noimage600``.

The rest of the file keeps the same BaseNewsScraper‑v2 glue and follows the
same coding style as the other modules.
"""

from datetime import datetime
from typing import Any, Dict, List, Sequence
from urllib.parse import urljoin, urlparse
import html
import json
import logging
import re

from bs4 import BeautifulSoup  # type: ignore – BeautifulSoup4

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind

logger = logging.getLogger(__name__)

# ───────────────────────────── helpers / constants ──────────────────────────
_MAX_PER_PAGE = 15
_SITE = "https://www.dailypioneer.com"

_WS_RE = re.compile(r"\s+")
_PLACEHOLDER_IMG = re.compile(r"noimage", re.I)
_DATE_RE = re.compile(r"^(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,? (\d{1,2}) (\w+) (\d{4})")
_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


def _clean(val: str | None) -> str | None:
    if not val:
        return None
    return _WS_RE.sub(" ", html.unescape(val)).strip() or None


def _iso_from_text(text: str | None) -> str | None:
    if not text:
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    day, month_name, year = int(m.group(1)), m.group(2), int(m.group(3))
    month = _MONTHS.get(month_name)
    if not month:
        return None
    try:
        return datetime(year, month, day).isoformat()
    except Exception:
        return None


def _section_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path.lstrip("/")
    parts = path.split("/", 2)
    if len(parts) >= 2 and parts[0].isdigit():
        return parts[1]
    return None

# ───────────────────────────────── scraper ──────────────────────────────────
class DailyPioneerScraper(BaseNewsScraper):
    """Scraper for **The Daily Pioneer** public search pages."""

    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML
    BASE_URL = f"{_SITE}/searchlist.php"

    HEADERS: Dict[str, str] = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    # ───────────────────────── public entry‑point ──────────────────────────
    def search(
        self,
        keyword: str,
        page: int = 1,
        size: int = 30,
        *,
        section: str | None = None,
        year: int | None = None,
        **kwargs: Any,
    ) -> List[Article]:
        if size > _MAX_PER_PAGE:
            logger.warning("DailyPioneer caps at %d results/page – trimming", _MAX_PER_PAGE)
            size = _MAX_PER_PAGE

        self.PARAMS = {
            "section": section or "",
            "adv": keyword,
            "yr": str(year or datetime.now().year),
            "page": str(page),
        }
        self.PAYLOAD = {}
        return super().search(keyword, page, size, **kwargs)[:size]

    # ────────────────────── parse HTML search page ────────────────────────
    def _parse_response(self, html_text: str):  # type: ignore[override]
        soup = BeautifulSoup(html_text, "lxml")
        arts: list[Article] = []

        # Hero card first (div.BigNews)
        if hero := soup.select_one("div.BigNews"):
            if art := self._extract_card(hero, hero_mode=True):
                arts.append(art)

        # Standard 14 cards (div.row.newsWrap)
        for card in soup.select("div.row.newsWrap"):
            if art := self._extract_card(card, hero_mode=False):
                arts.append(art)

        # Hydrate each thin card
        for art in arts:
            if not art.url:
                continue
            try:
                detail = self._hydrate(art.url)
            except Exception:  # pragma: no cover
                logger.exception("Hydration failed for %s", art.url)
                continue

            art.author = detail.get("author") or art.author
            art.content = detail.get("content") or art.content
            art.summary = detail.get("summary") or art.summary
            art.tags = detail.get("tags", art.tags)
            art.section = detail.get("section") or art.section
            art.published_at = detail.get("published_at") or art.published_at
            extra_media: list[MediaItem] = detail.get("media", [])
            seen = {m.url for m in art.media}
            art.media.extend(m for m in extra_media if m.url not in seen)

        return arts

    # ─────────────────────────── card helpers ────────────────────────────
    def _extract_card(self, node, *, hero_mode: bool) -> Article | None:
        h2 = node.find("h2")
        if not h2 or not h2.find("a"):
            return None
        rel = h2.find("a")["href"]
        url = urljoin(_SITE, rel)
        title = _clean(h2.get_text(strip=True))

        # image
        media: list[MediaItem] = []
        if hero_mode and (img := node.select_one("figure img")):
            src = img.get("data-src") or img.get("src")
            if src and not _PLACEHOLDER_IMG.search(src):
                media.append(MediaItem(url=src, caption=img.get("alt"), type="image"))
        elif not hero_mode and (thumb := node.select_one(".imageSize2 img[src]")):
            src = thumb["src"]
            if src and not _PLACEHOLDER_IMG.search(src):
                media.append(MediaItem(url=src, caption=thumb.get("alt"), type="image"))

        date_str, author = self._extract_meta(node)
        summary = None
        if p := node.find("p"):
            summary = _clean(p.get_text(" ", strip=True))

        section = _section_from_url(rel)

        return Article(
            title=title,
            published_at=_iso_from_text(date_str) or date_str,
            url=url,
            summary=summary,
            author=author,
            media=media,
            outlet="The Daily Pioneer",
            tags=[],
            section=section,
        )

    def _extract_meta(self, node):
        meta = node.find("div", class_="newsInfo")
        if not meta:
            return None, None
        parts = [p.strip() for p in meta.get_text("|", strip=True).split("|") if p.strip()]
        date_part = parts[0] if parts else None
        author_part = next((p for p in parts[1:] if p), None)
        return _clean(date_part), _clean(author_part)

    # ─────────────────────── article hydration ───────────────────────────
    def _hydrate(self, url: str) -> Dict[str, Any]:
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        out: Dict[str, Any] = {
            "author": None,
            "summary": None,
            "content": None,
            "tags": [],
            "published_at": None,
            "media": [],
            "section": None,
        }

        # 1) JSON‑LD first
        if ld := self._jsonld_extract(soup):
            out.update(ld)

        # 2) Fallback DOM selectors
        self._dom_fallback(soup, out, url)
        return out

    # ─────────────────────── JSON‑LD helpers ─────────────────────────────
    @staticmethod
    def _jsonld_extract(soup: BeautifulSoup) -> Dict[str, Any] | None:
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or ""
            try:
                data = json.loads(html.unescape(raw))
            except Exception:
                continue
            queue: list[Any] = [data]
            while queue:
                node = queue.pop()
                if isinstance(node, dict):
                    if node.get("@type") == "NewsArticle":
                        return DailyPioneerScraper._from_jsonld(node)
                    queue.extend(node.values())
                elif isinstance(node, list):
                    queue.extend(node)
        return None

    @staticmethod
    def _from_jsonld(d: Dict[str, Any]) -> Dict[str, Any]:
        # author
        author_name = None
        auth = d.get("author")
        if isinstance(auth, dict):
            author_name = auth.get("name")
        elif isinstance(auth, list):
            names = [a.get("name") if isinstance(a, dict) else str(a) for a in auth]
            author_name = ", ".join(n for n in names if n)
        elif isinstance(auth, str):
            author_name = auth

        # images
        imgs: list[str] = []
        match d.get("image"):
            case str(s):
                imgs.append(s)
            case list(lst):
                imgs.extend(lst)
            case dict(obj):
                if u := obj.get("url"):
                    imgs.append(u)
        media = [
            MediaItem(url=u, caption=None, type="image")
            for u in imgs
            if u and not _PLACEHOLDER_IMG.search(u)
        ]

        # tags
        tags: list[str] = []
        if kw := d.get("keywords"):
            if isinstance(kw, str):
                tags = [t.strip() for t in re.split(r",|\|", kw) if t.strip()]
            elif isinstance(kw, list):
                tags = [str(t).strip() for t in kw if str(t).strip()]

        return {
            "author": author_name,
            "summary": d.get("description"),
            "content": d.get("articleBody"),
            "tags": tags,
            "published_at": d.get("datePublished") or d.get("dateModified"),
            "media": media,
            "section": d.get("articleSection") or None,
        }

    # ───────────────────── DOM fallback selector soup ────────────────────
    @staticmethod
    def _dom_fallback(soup: BeautifulSoup, out: Dict[str, Any], url: str):
        # author
        if not out.get("author"):
            if el := soup.select_one(".newsInfo"):
                parts = [p.strip() for p in el.get_text("|", strip=True).split("|") if p.strip()]
                if len(parts) >= 2:
                    out["author"] = parts[1]
        # summary (first paragraph)
        if not out.get("summary"):
            body = soup.select_one("div.newsDetailedContent")
            if body and (p := body.find("p")):
                out["summary"] = _clean(p.get_text(" ", strip=True))
        # content
        if not out.get("content"):
            body = soup.select_one("div.newsDetailedContent")
            if body:
                for tag in body.find_all(["script", "style", "noscript"]):
                    tag.decompose()
                texts = [t.get_text(" ", strip=True) for t in body.find_all(["p", "li", "h2"]) if t.get_text(strip=True)]
                out["content"] = "\n".join(texts).strip() if texts else None
        # media – og:image first, then first inline img
        if not out.get("media"):
            images: list[MediaItem] = []
            if meta := soup.find("meta", property="og:image"):
                src = meta.get("content")
                if src and not _PLACEHOLDER_IMG.search(src):
                    images.append(MediaItem(url=src, caption=None, type="image"))
            if not images and (img := soup.select_one("div.newsDetailedContent img[src]")):
                src = img["src"]
                if src and not _PLACEHOLDER_IMG.search(src):
                    images.append(MediaItem(url=src, caption=img.get("alt"), type="image"))
            out["media"] = images
        # section (breadcrumb: second li > a)
        if not out.get("section"):
            crumb = soup.select_one("ul.list-unstyled li:nth-of-type(2) a")
            if crumb and crumb.get("href"):
                out["section"] = _section_from_url(crumb["href"]) or _clean(crumb.get_text(strip=True))
        if not out.get("section"):
            out["section"] = _section_from_url(url)

# ───────────────────────────── smoke‑test ────────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual run only
    logging.basicConfig(level="INFO")
    scraper = DailyPioneerScraper()
    arts = scraper.search("bangladesh", page=1, size=15, year=2025)
    for a in arts:
        print(f"{a.published_at} | {a.section} | {a.author} | {a.title}\n{a.url}\n{len(a.media)} media item(s)\n")
    print(f"Total {len(arts)} article(s)")
