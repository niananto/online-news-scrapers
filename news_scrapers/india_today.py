from __future__ import annotations

"""IndiaTodayScraper – keyword-based search scraper for *India Today*.

Currently supports only **search** via:
  https://www.indiatoday.in/api/ajax/loadmorecontent?key={keyword}&page={page}&page_type=searchlist&display={page_size}

Pagination starts at **0**. Hydration not yet implemented.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
import logging

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem

logger = logging.getLogger(__name__)

class IndiaTodayScraper(BaseNewsScraper):
    """Scraper for **India Today** keyword search results."""

    BASE_URL = "https://www.indiatoday.in/api/ajax/loadmorecontent"
    REQUEST_METHOD = "GET"

    HEADERS: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "referer": "https://www.indiatoday.in/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    def search(
        self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any
    ) -> List[Article]:
        # Convert to IndiaToday's 0-based pagination and clamp size to 20 max
        real_page = max(page - 1, 0)
        if size > 20:
            logger.warning("size must be ≤ 20, truncating to 20")
            size = 20
        self.PARAMS = {
            "key": keyword,
            "page": str(real_page),
            "page_type": "searchlist",
            "display": str(size),
        }
        self.PAYLOAD = {}
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, data: Dict[str, Any]) -> List[Article]:
        sections = data.get("data", {}).get("content", {})
        stories = sections.get("story", {}).get("listing", [])
        if not isinstance(stories, list):
            return []

        articles: List[Article] = []
        for item in stories:
            title = item.get("title_short")
            summary = item.get("description_short")
            url_path = item.get("canonical_url")
            full_url = urljoin("https://www.indiatoday.in", url_path) if url_path else None
            published = item.get("datetime_published")

            # Author(s)
            authors = item.get("author", [])
            author = ", ".join(a.get("title") for a in authors if a.get("title")) if authors else None

            # Section
            section = None
            if cats := item.get("category_detail"):
                section = ", ".join(c.get("title") for c in cats if c.get("title"))

            # Media
            media: List[MediaItem] = []
            if img_url := item.get("image_small"):
                media.append(MediaItem(url=img_url, caption=item.get("image_small_alt_text"), type="image"))

            articles.append(
                Article(
                    title=title,
                    published_at=published,
                    url=full_url,
                    summary=summary,
                    content=None,
                    author=author,
                    media=media,
                    outlet="India Today",
                    tags=[],
                    section=section,
                )
            )
        return articles


# ────────────────────────────── local demo ──────────────────────────────
if __name__ == "__main__":
    scraper = IndiaTodayScraper()
    results = scraper.search("bangladesh", page=1, size=50)
    for art in results:
        print(f"{art.published_at} – {art.outlet} – {art.author} – {art.title}\n{art.url}\n{art.summary}\n")
    print(f"\nTotal: {len(results)} articles.")
