'''
Scraper for The Telegraph India.
'''
import os
import json
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class TelegraphIndiaScraper(BaseNewsScraper):
    """Scraper for **The Telegraph India** via Google Custom Search."""

    BASE_URL = "https://www.googleapis.com/customsearch/v1"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.cx = "partner-pub-9104455251217860:2k8fyg-64or"  # The Telegraph India CSE ID
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
                outlet="The Telegraph India",
                media=media_items,
            )

            if pagemap := item.get("pagemap"):
                if metatags := pagemap.get("metatags"):
                    if len(metatags) > 0:
                        meta = metatags[0]
                        if news_keywords := meta.get("news_keywords"):
                            article.tags = [tag.strip() for tag in news_keywords.split(',')]

            if article.url:
                try:
                    details = self._fetch_article_details(article.url)
                    article.author = details.get("author") or article.author
                    article.content = details.get("content") or article.content
                    article.published_at = details.get("published_at") or article.published_at
                except Exception as e:
                    logger.warning(f"Failed to hydrate article {article.url}: {e}")

            articles.append(article)
        return articles

    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """Fetch and parse the full article content."""
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
        }
        resp = self.session.get(url, headers=headers, timeout=self.timeout, proxies=self.proxies)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        details: Dict[str, Any] = {
            "author": None,
            "content": None,
            "published_at": None,
        }

        # Extract from JSON-LD script tag
        ld_json_script = soup.find("script", type="application/ld+json")
        if ld_json_script:
            try:
                ld_json_data = json.loads(ld_json_script.string)
                if isinstance(ld_json_data, list):
                    ld_json_data = ld_json_data[0]
                if ld_json_data.get("@type") == "NewsArticle":
                    details["author"] = ld_json_data.get("author", {}).get("name")
                    details["published_at"] = ld_json_data.get("datePublished")
            except (json.JSONDecodeError, IndexError):
                logger.warning(f"Could not parse JSON-LD for {url}")

        # Extract content
        if content_article := soup.find("article", id="contentbox"):
            paragraphs = content_article.find_all("p")
            # Exclude the last paragraph if it's the syndicated feed notice
            if paragraphs and "not been edited by The Telegraph Online staff" in paragraphs[-1].get_text():
                paragraphs = paragraphs[:-1]
            details["content"] = " ".join(p.get_text(strip=True) for p in paragraphs)

        return details


if __name__ == "__main__":
    scraper = TelegraphIndiaScraper()
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
