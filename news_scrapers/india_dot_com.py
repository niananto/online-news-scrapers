from __future__ import annotations

"""India.com *topic* page scraper – **HTML** search variant.

This scraper plugs into the shared :class:`news_scrapers.base.BaseNewsScraper`
workflow **without** rewriting its public ``search`` logic.  The trick is a
custom :py:meth:`_fetch_json` that actually downloads raw HTML instead of JSON
and hands that straight to :py:meth:`_parse_response` for BeautifulSoup
processing.

Key design points
-----------------
* **REQUEST_METHOD = "GET"** – matches the remote endpoint.
* **Dynamic ``BASE_URL``** – every invocation of :py:meth:`search` rewrites
  ``self.BASE_URL`` to ``https://www.india.com/topic/<keyword>/page/<page>/``
  *before* delegating back to ``super().search``.
* **Size guard** – the listing shows *exactly 24* articles once the leading 8
  *Photos/Videos* widgets are skipped.  A friendly warning is logged when
  callers request more than 24.

The resulting :class:`Article` list is thin (no body text/tag hydration yet)
--- identical to the other “search‑only” scrapers.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
import datetime as _dt
import logging
import re

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem

logger = logging.getLogger(__name__)


class IndiaComScraper(BaseNewsScraper):
    """Scraper for *India.com* **topic** listings (search‑phase only)."""

    # Will be overwritten per‑call inside ``search``
    BASE_URL: str = "https://www.india.com/topic/"
    REQUEST_METHOD: str = "GET"

    DEFAULT_HEADERS: Dict[str, str] = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    # ───────────────────────────── public override ────────────────────────────
    def search(  # type: ignore[override] – match siblings’ flexible signature
        self,
        keyword: str,
        page: int = 1,
        size: int = 30,
        **kwargs: Any,
    ) -> List[Article]:
        # India.com exposes 24 *news* cards per listing page (after skipping
        # the Photos+Videos widgets). Warn and clamp when callers ask for more.
        if size > 24:
            logger.warning(
                "India.com returns ≤ 24 articles per page; continuing with 24 …"
            )
            size = 24

        # Mutate BASE_URL *before* delegating so the superclass uses the full
        # page URL when calling ``_fetch_json``.
        self.BASE_URL = f"https://www.india.com/topic/{keyword}/page/{max(page,1)}/"

        return super().search(keyword, page, size, **kwargs)

    # ───────────────────────────── Base hooks ────────────────────────────────
    def _build_params(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """India.com listing pages need **no** query‑string parameters."""
        return {}

    def _build_payload(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """GET‑only endpoint → empty body."""
        return {}

    # ------------------------------------------------------------------
    # fetch & parse – HTML flavour
    # ------------------------------------------------------------------
    def _fetch_json(self, url: str, params: Dict[str, Any], payload: Dict[str, Any]):  # noqa: D401
        """Download raw HTML instead of JSON and hand it back verbatim."""
        resp = self.session.get(
            url,
            headers=self.DEFAULT_HEADERS,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        resp.raise_for_status()
        return resp.text  # ← will be parsed by ``_parse_response``

    def _parse_response(self, html_text: str):  # type: ignore[override]
        """Convert the listing HTML into a list of :class:`Article` objects."""
        soup = BeautifulSoup(html_text, "lxml")
        return self._parse_listing(soup)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_listing(soup: BeautifulSoup) -> List[Article]:
        """Extract 24 *news* cards, skipping the leading Photos/Videos."""

        # The actual news cards live under the *… News* section within the
        # left‑hand column (``section.lhs-col``).
        cards = soup.select("section.lhs-col article.repeat-box")

        articles: List[Article] = []
        for box in cards:
            # Defensive skip – Photos/Videos cards have no <h2><a> combo.
            if not (h2 := box.find("h2")) or not (a := h2.find("a")):
                continue

            art = Article(outlet="India.com")

            # ── title & URL ────────────────────────────────────────────
            art.title = h2.get_text(strip=True)
            art.url = a.get("href")

            # ── lead image ────────────────────────────────────────────
            if (img := box.select_one("div.photo img")):
                src = img.get("data-src") or img.get("src")
                if src and not src.endswith("/1x1.svg") and "default-big.svg" not in src:
                    art.media.append(MediaItem(url=src, caption=img.get("alt"), type="image"))

            # ── author & timestamp ────────────────────────────────────
            date_el = box.select_one(".published-by .date")
            if date_el:
                if (author_a := date_el.find("a")):
                    art.author = author_a.get_text(strip=True)
                iso_ts = IndiaComScraper._extract_iso_date(date_el.get_text(" ", strip=True))
                art.published_at = iso_ts

            # ── summary ──────────────────────────────────────────────
            summary_el = date_el.find_next("p") if date_el else None
            if summary_el and summary_el not in date_el.parents:
                art.summary = summary_el.get_text(" ", strip=True)

            articles.append(art)

        return articles

    # ------------------------------------------------------------------
    # tiny date util
    # ------------------------------------------------------------------
    _DATE_RE = re.compile(
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)", re.I
    )

    @classmethod
    def _extract_iso_date(cls, raw: str) -> Optional[str]:
        """Convert *raw* (e.g. ``'July 9, 2025 7:54 AM IST'``) → ISO‑8601."""
        m = cls._DATE_RE.search(raw)
        if not m:
            return None
        try:
            dt = _dt.datetime.strptime(m.group(1), "%B %d, %Y %I:%M %p")
            dt = dt.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=5, minutes=30)))  # IST
            return dt.isoformat()
        except Exception:
            return None


# ───────────────────────────── tiny smoke‑test ─────────────────────────────
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)

    scraper = IndiaComScraper()
    arts = scraper.search("bangladesh", page=1, size=30)

    for art in arts:
        print(art.published_at, "–", art.title)
    print("Fetched", len(arts), "articles.")
