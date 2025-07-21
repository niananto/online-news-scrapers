'''
Scraper for The Hindu.
'''
import os
import json
from typing import Any, Dict, List

from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class TheHinduScraper(BaseNewsScraper):
    """Scraper for **The Hindu** via Google Custom Search."""

    BASE_URL = "https://www.googleapis.com/customsearch/v1"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.cx = "264d7caeb1ba04bfc"  # The Hindu CSE ID
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env file")

    def search(self, keyword: str, page: int = 1, size: int = 10, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""
        if size > 10:
            logger.warning("Google Custom Search API allows a maximum of 10 items per page. Proceeding with size=10.")
            size = 10
        start_index = (page - 1) * size + 1
        self.PARAMS = {"key": self.api_key, "cx": self.cx, "q": keyword, "start": start_index, "sort": "date"}
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Convert the JSON response into a list of `Article` objects."""
        articles: list[Article] = []
        if not json_data or "items" not in json_data:
            return articles

        for item in json_data["items"]:
            media_items = []
            if pagemap := item.get("pagemap"):
                if cse_thumbnail := pagemap.get("cse_thumbnail"):
                    if len(cse_thumbnail) > 0 and cse_thumbnail[0].get("src"):
                        media_items.append(MediaItem(url=cse_thumbnail[0]["src"], type="image"))
                elif cse_image := pagemap.get("cse_image"):
                    if len(cse_image) > 0 and cse_image[0].get("src"):
                        media_items.append(MediaItem(url=cse_image[0]["src"], type="image"))

            article = Article(
                title=item.get("title"),
                url=item.get("link"),
                summary=item.get("snippet"),
                outlet="The Hindu",
                media=media_items,
            )

            if pagemap := item.get("pagemap"):
                if metatags := pagemap.get("metatags"):
                    if len(metatags) > 0:
                        meta = metatags[0]
                        article.published_at = meta.get("article:published_time")
                        article.author = meta.get("article:author")
                        if news_keywords := meta.get("news_keywords"):
                            article.tags = [tag.strip() for tag in news_keywords.split(',')]

            # Placeholder for fetching full article details
            # if article.url:
            #     try:
            #         details = self._fetch_article_details(article.url)
            #         article.content = details.get("content")
            #     except Exception as e:
            #         logger.warning(f"Failed to hydrate article {article.url}: {e}")

            articles.append(article)
        return articles


if __name__ == "__main__":
    scraper = TheHinduScraper()
    try:
        found_articles = scraper.search("bangladesh")
        for art in found_articles:
            print(f"Title: {art.title}")
            print(f"  URL: {art.url}")
            print(f"  Author: {art.author}")
            print(f"  Published At: {art.published_at}")
            print(f"  Summary: {art.summary}")
            if art.media:
                print(f"  Media: {art.media[0].url}")
            print("-" * 20)
    finally:
        scraper.quit_browser()
