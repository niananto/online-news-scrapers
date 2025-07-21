'''
Scraper for the BBC.
'''
import os
import json
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class BBCScraper(BaseNewsScraper):
    """Scraper for **BBC**."""

    BASE_URL = "https://www.bbc.com/search"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML
    HEADERS = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'priority': 'u=0, i',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

    def search(self, keyword: str, page: int = 1, size: int = 10, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""
        self.PARAMS = {"q": keyword, "page": page}
        # The 'size' parameter is not directly supported by the BBC search URL,
        # but we keep it in the signature for consistency.
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, html: str) -> List[Article]:
        """Convert the HTML response into a list of `Article` objects."""
        soup = BeautifulSoup(html, "html.parser")
        articles: list[Article] = []

        next_data_script = soup.find("script", id="__NEXT_DATA__")
        if not next_data_script:
            return articles

        try:
            data = json.loads(next_data_script.string)
            results = list(data.get("props", {}).get("pageProps", {}).get("page", {}).values())[0].get("results", [])
        except (json.JSONDecodeError, AttributeError):
            return articles

        for item in results:
            title = item.get("title")
            relative_url = item.get("href")
            if not relative_url:
                continue
            url = f"https://www.bbc.com{relative_url}"
            summary = item.get("description")
            
            timestamp = item.get("metadata", {}).get("firstUpdated")
            if timestamp:
                # Convert timestamp from milliseconds to ISO 8601 format
                published_at = datetime.fromtimestamp(timestamp / 1000).isoformat()
            else:
                published_at = None

            media_items = []
            if image_data := item.get("image"):
                if image_model := image_data.get("model"):
                    if image_blocks := image_model.get("blocks"):
                        if image_src := image_blocks.get("src"):
                            media_items.append(MediaItem(url=image_src, type="image"))

            article = Article(
                title=title,
                url=url,
                summary=summary,
                published_at=published_at,
                outlet="BBC",
                media=media_items,
            )

            articles.append(article)
        return articles


if __name__ == "__main__":
    scraper = BBCScraper()
    try:
        found_articles = scraper.search("bangladesh", page=2)
        for art in found_articles:
            print(f"Title: {art.title}")
            print(f"  URL: {art.url}")
            print(f"  Published At: {art.published_at}")
            print(f"  Summary: {art.summary}")
            if art.media:
                print(f"  Media: {art.media[0].url}")
            print("-" * 20)
    finally:
        scraper.quit_browser()
