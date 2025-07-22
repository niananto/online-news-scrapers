
import os
import json
from typing import Any, Dict, List

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class TheDiplomatScraper(BaseNewsScraper):
    """Scraper for **The Diplomat** via Google Custom Search."""

    BASE_URL = "https://www.googleapis.com/customsearch/v1"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON
    USE_BROWSER = True

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

            if article.url:
                try:
                    self._init_browser()
                    details = self._fetch_article_details(article.url)
                    article.author = details.get("author")
                    article.content = details.get("content")
                    article.published_at = details.get("published_at")
                except Exception as e:
                    logger.warning(f"Failed to hydrate article {article.url}: {e}")

            articles.append(article)
        return articles

    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """Fetch and parse the full article content."""
        soup = BeautifulSoup(self._fetch_via_browser(url, {}), "html.parser")

        details: Dict[str, Any] = {
            "author": None,
            "content": None,
            "published_at": None,
        }

        # Extract content
        content_section = soup.find("section", id="tda-gated-body")
        if content_section:
            details["content"] = content_section.get_text(strip=True)

        # Extract metadata from ld+json
        ld_json_script = soup.find("script", type="application/ld+json")
        if ld_json_script:
            try:
                ld_json_data = json.loads(ld_json_script.string)
                if isinstance(ld_json_data, list):
                    ld_json_data = ld_json_data[0]

                if author_data := ld_json_data.get("author"):
                    if isinstance(author_data, list):
                        details["author"] = ", ".join(author.get("name") for author in author_data if author.get("name"))
                    elif isinstance(author_data, dict):
                        details["author"] = author_data.get("name")

                details["published_at"] = ld_json_data.get("datePublished")
            except json.JSONDecodeError:
                logger.warning(f"Could not parse ld+json for {url}")

        return details


if __name__ == "__main__":
    scraper = TheDiplomatScraper()
    try:
        found_articles = scraper.search("bangladesh")
        for art in found_articles:
            print(f"Title: {art.title}")
            print(f"  URL: {art.url}")
            print(f"  Author: {art.author}")
            print(f"  Published At: {art.published_at}")
            print(f"  Summary: {art.summary}")
            print(f"  Content: {(art.content or '')[:200]}...")
            if art.media:
                print(f"  Media: {art.media[0].url}")
            print("-" * 20)
    finally:
        scraper.quit_browser()
