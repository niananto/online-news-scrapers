from __future__ import annotations
"""SouthAsiaMonitorScraper – section search + article hydration for *SouthAsiaMonitor.org*.

Key points
~~~~~~~~~~
* **Listing URL** – ``https://www.southasiamonitor.org/<section>?page=<n>`` –
  pagination starts at **0** (unlike most other outlets).
* Articles are marked‑up in several templates; we unify them by selecting
  the *h3 > a* inside either ``div.news-block-four`` or
  ``div.thumbnail[\_big|\_small]``.
* Each article page embeds the full body inside ``div.news-detail``; the
  date/time lives in ``span.wrap-date-location``.

This scraper follows the new :class:`news_scrapers.base.BaseNewsScraper` v2
interface and mirrors the style of the existing HTML‑oriented scrapers
(e.g. :pyclass:`IndiaDotComScraper`).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
import logging
import re

from bs4 import BeautifulSoup  # type: ignore – BeautifulSoup4

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind

logger = logging.getLogger(__name__)

# ──────────────────────────── constants / helpers ───────────────────────────
_TZ_BD = timezone(timedelta(hours=6))  # UTC+06:00 – Dhaka / Asia
_DATE_PATTERNS = (
    "%b %d, %Y",      # May 16, 2022
    "%B %d, %Y",     # September 9, 2023
)


def _to_iso(date_str: str | None) -> Optional[str]:
    """Best‑effort *Mon DD, YYYY* → ISO‑8601 (UTC+06:00)."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in _DATE_PATTERNS:
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=_TZ_BD)
            return dt.isoformat()
        except Exception:
            continue
    return None


def _section_from_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    path = urlparse(url).path.lstrip("/")
    if path.startswith("index.php/"):
        path = path[10:]  # drop leading *index.php/*
    return path.split("/", 1)[0] if path else None


# ───────────────────────────────── scraper class ────────────────────────────
class SouthAsiaMonitorScraper(BaseNewsScraper):
    """Scraper for **South Asia Monitor** country/section pages."""

    REQUEST_METHOD: str = "GET"
    RESPONSE_KIND: ResponseKind = ResponseKind.HTML  # listings are raw HTML

    BASE_URL: str = "https://www.southasiamonitor.org/"  # overridden per call

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
        section: str = "bangladesh",
        page: int = 1,
        size: int = 50,
        **kwargs: Any,
    ) -> List[Article]:
        """Return *size* hydrated articles from *section* and *page* (1‑based).

        The remote site uses **0‑based** pagination – we translate transparently.
        """
        if size > 16:
            logger.warning("The Statesman returns max 16 results per page – truncating from %s",size)
            size = 16

        remote_page = max(page - 1, 0)  # SAM expects *?page=0* for the 1st page

        # Point *BASE_URL* at the listing and clear PARAMS/PAYLOAD for the base
        # class machinery.
        original_base = self.BASE_URL
        self.BASE_URL = f"https://www.southasiamonitor.org/{section}?page={remote_page}"
        self.PARAMS = {}
        self.PAYLOAD = {}

        try:
            articles = super().search(section, page, size, **kwargs)
        finally:
            self.BASE_URL = original_base  # restore for caller re‑use
        return articles

    # ───────────────────── parse listing + hydrate ────────────────────────
    def _parse_response(self, html: str) -> List[Article]:  # noqa: D401
        soup = BeautifulSoup(html, "lxml")
        listing = self._parse_listing(soup)
        # Hydrate each article with the full page (content, author, …)
        for art in listing:
            if not art.url:
                continue
            try:
                details = self._fetch_article_details(art.url)
            except Exception:  # pragma: no cover – network/HTML glitches
                logger.exception("Failed to hydrate %s", art.url)
                continue

            if details:
                art.content = details.get("content") or art.content
                art.summary = details.get("summary") or art.summary
                art.author = details.get("author") or art.author
                art.tags = details.get("tags", art.tags)
                art.published_at = details.get("published_at") or art.published_at
                extra_media: List[MediaItem] = details.get("media", [])
                art.media.extend(m for m in extra_media if m.url not in {mi.url for mi in art.media})

        return listing

    # ───────────────────────────── listing helper ──────────────────────────
    def _parse_listing(self, soup: BeautifulSoup) -> List[Article]:
        # Unified selector for the various card templates
        anchors = soup.select(
            "div.news-block-four h3 > a, div.thumbnail_small h3 > a, div.thumbnail_big h3 > a"
        )
        articles: List[Article] = []
        for a in anchors:
            title = a.get_text(strip=True)
            if not title:
                continue  # skip image‑only anchors

            url = urljoin("https://www.southasiamonitor.org", a.get("href"))
            card = a.find_parent("div.content-inner") or a.find_parent("div.caption")
            date_iso: Optional[str] = None
            summary: Optional[str] = None
            if card:
                if (li := card.select_one("ul.post-meta li")):
                    date_iso = _to_iso(li.get_text(" ", strip=True))
                if (p := card.select_one("div.text p")):
                    summary = p.get_text(" ", strip=True)

            art = Article(
                title=title,
                published_at=date_iso,
                url=url,
                summary=summary,
                outlet="South Asia Monitor",
                section=_section_from_url(url),
            )
            articles.append(art)

            if len(articles) >= 50:
                break  # hard safety – listing rarely shows more than ≈40 items
        return articles

    # ─────────────────────────── article hydration ─────────────────────────
    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        details: Dict[str, Any] = {}

        # Title redundantly available – ignore.

        # Published date
        if (span := soup.select_one("span.wrap-date-location")):
            details["published_at"] = _to_iso(span.get_text(" ", strip=True))

        # Summary (sub‑heading)
        if (h5 := soup.find("h5", class_="title")):
            details["summary"] = h5.get_text(" ", strip=True)

        # Full body
        if (div_body := soup.select_one("div.news-detail")):
            paragraphs = [p.get_text(" ", strip=True) for p in div_body.find_all("p")]
            body = "\n".join([p for p in paragraphs if p])
            details["content"] = body or None

        # Hero image – first <picture> inside .show-caption
        if (fig := soup.select_one(".show-caption picture img")):
            src = fig.get("src")
            if src:
                details["media"] = [MediaItem(url=src, caption=fig.get("alt"), type="image")]

        # Tags – extract from breadcrumb 3rd/4th item if any
        crumbs = [li.get_text(strip=True) for li in soup.select("ol.breadcrumb li")]
        if len(crumbs) >= 2:
            # skip *Home*; last item is title – middle crumbs are tags / sections
            details["tags"] = crumbs[1:-1]
        return details


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    logging.basicConfig(level="INFO")
    scraper = SouthAsiaMonitorScraper()
    arts = scraper.search("bangladesh", page=1, size=10)
    for art in arts:
        print(f"{art.published_at} – {art.title}\n{art.url}\nTags: {art.tags}\n")
