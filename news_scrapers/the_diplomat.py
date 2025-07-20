
import os
from typing import Any, Dict, List

from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class TheDiplomatScraper(BaseNewsScraper):
    """Scraper for **The Diplomat** via Google Custom Search."""

    BASE_URL = "https://www.googleapis.com/customsearch/v1"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.cx = "006972344228181832854:w07k6emi2wk"
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env file")

    def search(self, keyword: str, page: int = 1, size: int = 10, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""
        if size > 10:
            logger.warning("Google Custom Search API allows a maximum of 10 items per page. Proceeding with size=10.")
            size = 10
        start_index = (page - 1) * size + 1
        self.PARAMS = {"key": self.api_key, "cx": self.cx, "q": keyword, "start": start_index, "num": size}
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

            article = Article(
                title=item.get("title"),
                url=item.get("link"),
                summary=item.get("snippet"),
                outlet="The Diplomat",
                media=media_items,
            )
            articles.append(article)
        return articles


if __name__ == "__main__":
    scraper = TheDiplomatScraper()
    found_articles = scraper.search("bangladesh", size=20)  # test the guard
    for art in found_articles:
        print(f"Found article: {art.title}")
        print(f"  URL: {art.url}")
        print(f"  Summary: {art.summary}")
        if art.media:
            print(f"  Media: {art.media[0].url}")

