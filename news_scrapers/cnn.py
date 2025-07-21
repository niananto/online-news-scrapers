import json
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class CNNScraper(BaseNewsScraper):
    """Scraper for **CNN**."""

    BASE_URL = "https://search.prod.di.api.cnn.io/content"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON
    HEADERS = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'origin': 'https://edition.cnn.com',
        'pragma': 'no-cache',
        'referer': 'https://edition.cnn.com/',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross-site',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

    def search(self, keyword: str, page: int = 1, size: int = 10, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""
        self.PARAMS = {
            'q': keyword,
            'size': str(size),
            'from': str((page - 1) * size),
            'page': str(page),
            'sort': 'newest',
            'types': 'article',
            'request_id': 'stellar-search-6897f480-d5a0-45e3-b409-6fa04596eaf2', # This might need to be dynamic or removed if not critical
            'site': 'cnn',
        }
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, json_response: Dict[str, Any]) -> List[Article]:
        """Convert the JSON response into a list of `Article` objects."""
        articles: List[Article] = []
        results = json_response.get("result", [])

        for item in results:
            title = item.get("headline")
            url = item.get("url")
            summary = item.get("body")
            published_at = None
            if item.get("lastModifiedDate"):
                try:
                    published_at = datetime.fromisoformat(item["lastModifiedDate"].replace("Z", "+00:00")).isoformat()
                except ValueError:
                    pass

            media_items = []
            if item.get("thumbnail"):
                media_items.append(MediaItem(url=item["thumbnail"], type="image"))

            article = Article(
                title=title,
                url=url,
                summary=summary,
                published_at=published_at,
                outlet="CNN",
                media=media_items,
                author=None, # Author not available in search results
            )
            articles.append(article)
        return articles

    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """CNN search API provides enough details, no need for separate article fetching."""
        return {}


if __name__ == "__main__":
    scraper = CNNScraper()
    try:
        # Test search
        articles = scraper.search(keyword="bangladesh", size=10)
        for article in articles:
            print(f"Title: {article.title}")
            print(f"URL: {article.url}")
            print(f"Summary: {article.summary}")
            print(f"Published At: {article.published_at}")
            print(f"Outlet: {article.outlet}")
            print(f"Media: {article.media}")
            print(f"Author: {article.author}")
            print(f"Content: {article.content}")
            print("---")

    finally:
        scraper.quit_browser()
