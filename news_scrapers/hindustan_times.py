from __future__ import annotations

from typing import Any, Dict, List

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem


class HindustanTimesScraper(BaseNewsScraper):
    """Scraper for Hindustan Times search API."""

    BASE_URL = "https://api.hindustantimes.com/api/articles/search"

    DEFAULT_HEADERS: Dict[str, str] = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/json",
        "origin": "https://www.hindustantimes.com",
        "referer": "https://www.hindustantimes.com/search",
        "user-agent": "Mozilla/5.0 (compatible; ShottifyBot/1.0)",
    }

    def _build_payload(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """Render the JSON body expected by Hindustan Times."""

        return {
            "searchKeyword": keyword,
            "page": str(page),
            "size": str(size),
            "type": kwargs.get("type", "story"),
        }

    def _parse_response(self, j: Dict[str, Any]) -> List[Article]:
        """Map Hindustan Times JSON → Article objects."""

        raw_list = j.get("content") if j else []
        if not isinstance(raw_list, list):
            return []

        articles: list[Article] = []
        for item in raw_list:
            meta = item.get("metadata", {})
            media_items: list[MediaItem] = []
            lead_media = item.get("leadMedia") or item.get("image")
            if lead_media and lead_media.get("image"):
                img_dict = lead_media["image"]["images"]
                # pick the highest‑res available
                url = img_dict.get("original") or next(iter(img_dict.values()), None)
                if url:
                    media_items.append(
                        MediaItem(url=url, caption=lead_media.get("caption"), type="image")
                    )

            # Basic body extraction – the API gives first para text in listElement[0].
            content_body = None
            if item.get("listElement"):
                paragraphs = [
                    el.get("paragraph", {}).get("body", "")
                    for el in item["listElement"]
                    if el.get("type") == "paragraph"
                ]
                content_body = "\n".join(paragraphs).strip() or None

            art = Article(
                title=item.get("title") or item.get("headline"),
                published_at=item.get("firstPublishedDate"),
                url=meta.get("canonicalUrl") or meta.get("url") or item.get("url"),
                content=content_body,
                summary=item.get("quickReadSummary") or item.get("summary"),
                author=(meta.get("authors") or meta.get("author") or None),
                media=media_items,
                outlet="Hindustan Times",
                tags=[tag for tag in (meta.get("keywords") or []) if isinstance(tag, str)],
                section=meta.get("sectionName") or meta.get("section"),
            )
            articles.append(art)
        return articles


# ─────────────────── tiny demo ───────────────────

if __name__ == "__main__":  # pragma: no cover
    scraper = HindustanTimesScraper()
    articles = scraper.search("bangladesh", page=1, size=200)
    for article in articles:
        print(f"{article.published_at} – {article.author} - {article.title}\n{article.url}\n{article.summary}\n"
              f"{article.media}\n{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")