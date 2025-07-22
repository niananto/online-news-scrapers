import os
import json
import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class WionScraper(BaseNewsScraper):
    """Scraper for **Wion News** via Google Custom Search."""

    BASE_URL = "https://www.googleapis.com/customsearch/v1"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.cx = "006054055338965708568:09spwrlibei"  # Wion News CSE ID
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

            article = Article(
                title=item.get("title"),
                url=item.get("link"),
                summary=item.get("snippet"),
                outlet="Wion News",
                media=media_items,
            )

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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        }
        resp = self.session.get(url, headers=headers, timeout=self.timeout, proxies=self.proxies)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        details: Dict[str, Any] = {
            "author": None,
            "content": None,
            "published_at": None,
        }

        # Extract metadata from DataLayer script
        data_layer_script = soup.find("script", id="DataLayer")
        if data_layer_script:
            try:
                # Extract the JSON string from within the dataLayer array
                json_str_match = re.search(r'dataLayer=\[({.*?})\];', data_layer_script.string, re.DOTALL)
                if json_str_match:
                    json_string = json_str_match.group(1).replace("'", '"')
                    ld_json_data = json.loads(json_string)
                    details["author"] = ld_json_data.get("author_name")
                    details["published_at"] = ld_json_data.get("publish_date")
            except json.JSONDecodeError:
                logger.warning(f"Could not parse DataLayer JSON for {url}")

        # Extract content from __NEXT_DATA__ script tag
        next_data_script = soup.find("script", id="__NEXT_DATA__", type="application/json")

        if next_data_script and next_data_script.string:
            try:
                next_data = json.loads(next_data_script.string)
                
                # Prioritize props.pageProps.data.newsdetail.safe_content
                content_html = next_data.get("props", {}).get("pageProps", {}).get("data", {}).get("newsdetail", {}).get("safe_content")
                
                if not content_html:
                    # Fallback to props.pageProps.data.newsdetail.content if safe_content is not found
                    content_html = next_data.get("props", {}).get("pageProps", {}).get("data", {}).get("newsdetail", {}).get("content")

                if not content_html:
                    # Fallback for video posts: props.pageProps.data.videoDetails.summary
                    content_html = next_data.get("props", {}).get("pageProps", {}).get("data", {}).get("videoDetail", {}).get("summary")

                if content_html:
                    details["content"] = BeautifulSoup(content_html, "html.parser").get_text(separator=" ", strip=True)

            except json.JSONDecodeError:
                logger.warning(f"Could not parse __NEXT_DATA__ JSON for {url}")

        return details


if __name__ == "__main__":
    scraper = WionScraper()
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
