from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urljoin

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem


class BusinessStandardScraper(BaseNewsScraper):
    """Scraper for Business‑Standard public search API."""

    BASE_URL = "https://apibs.business-standard.com/search/"
    REQUEST_METHOD = "GET"  # Base class will honour this instead of POST

    DEFAULT_HEADERS: Dict[str, str] = {
        "accept": "application/json",
        "origin": "https://www.business-standard.com",
        "referer": "https://www.business-standard.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }

    IMG_PREFIX = "https://www.business-standard.com"  # image_path is relative
    URL_PREFIX = "https://www.business-standard.com"  # article_url is relative

    def _build_params(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """Return query‑param dict for the GET request."""

        return {
            "type": kwargs.get("type", "news"),
            "limit": str(size),
            "page": str(page),
            "keyword": keyword,
        }

    def _build_payload(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """Return empty dictionary as Business Standard requires a GET request."""

        return {}

    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Translate the JSON payload into ``Article`` objects."""

        raw_list = json_data.get("data", {}).get("news", []) if json_data else []
        if not isinstance(raw_list, list):
            return []

        articles: list[Article] = []
        for item in raw_list:
            # Build full URL and image path
            url_path: str | None = item.get("article_url")
            full_url = urljoin(self.URL_PREFIX, url_path) if url_path else None

            img_path: str | None = item.get("image_path")
            full_img = urljoin(self.IMG_PREFIX, img_path) if img_path else None
            media_items = (
                [MediaItem(url=full_img, caption=None, type="image")] if full_img else []
            )

            # Epoch seconds → ISO8601 handled by dataclass or base post‑proc
            published_raw = item.get("published_date")

            # Derive section from first segment of article_url ("/companies/news/…")
            section = None
            if url_path and url_path.startswith("/"):
                seg = url_path.split("/", 2)[1]
                section = seg or None

            art = Article(
                title=item.get("heading1"),
                published_at=published_raw,
                url=full_url,
                content=None,  # not fetched in this lightweight pass
                summary=item.get("sub_heading"),
                author=None,  # field not present in search API
                media=media_items,
                outlet="Business Standard",
                tags=[],
                section=section,
            )
            articles.append(art)
        return articles


# ─────────────────── tiny demo ───────────────────

if __name__ == "__main__":  # pragma: no cover
    scraper = BusinessStandardScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles[:5]:
        print(
            f"{article.published_at} – {article.title}\n{article.url}\n"
            f"{article.summary}\n{article.media}\n"
        )
    print(f"{len(articles)} articles found")
