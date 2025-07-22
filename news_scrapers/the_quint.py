from __future__ import annotations

"""The Quint keyword-search scraper."""

import html
import re
import json
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind


class TheQuintScraper(BaseNewsScraper):
    """Scraper for **The Quint** public search API."""

    BASE_URL = "https://www.thequint.com/api/v1/advanced-search"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON
    
    HEADERS: Dict[str, str] = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": "https://www.thequint.com/search?q=Bangladesh",
        "sec-ch-ua": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Google Chrome\";v=\"138\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }

    def search(
        self, keyword: str, page: int = 1, size: int = 8, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS, then delegate to the new base `search()`."""
        if size > 8:
            print("The Quint returns max 8 results per page – truncating from %s", size)
            size = 8

        self.PARAMS = {
            "fields": "headline,subheadline,slug,url,hero-image-s3-key,hero-image-caption,hero-image-metadata,first-published-at,last-published-at,alternative,published-at,authors,author-name,author-id,sections,story-template,metadata",
            "offset": (page - 1) * size,
            "limit": size,
            "q": keyword,
            "sort": "latest-published",
        }
        return super().search(keyword, page, size, **kwargs)

    @staticmethod
    def _clean_html(raw: str | None) -> str | None:
        if not raw:
            return None
        raw_unescaped: str = html.unescape(raw)
        text: str = BeautifulSoup(raw_unescaped, "lxml").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None

    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Convert the JSON response into a list of `Article` objects."""
        articles: list[Article] = []
        items = json_data.get("items", [])

        for item in items:
            title = item.get("headline")
            url = item.get("url")
            summary = item.get("subheadline")
            
            published_at = item.get("published-at")
            if published_at:
                try:
                    published_at = datetime.fromtimestamp(published_at / 1000).isoformat()
                except (TypeError, ValueError):
                    published_at = None

            author = item.get("author-name")
            
            image_url = None
            if item.get("hero-image-s3-key"):
                image_url = f"https://media.assettype.com/{item.get('hero-image-s3-key')}"

            media_items = []
            if image_url:
                media_items.append(MediaItem(url=image_url, type="image"))

            tags = [tag.get("name") for tag in item.get("tags", []) if tag.get("name")]

            section = None
            if item.get("sections") and len(item["sections"]) > 0:
                section = item["sections"][0].get("name")

            article = Article(
                title=title,
                published_at=published_at,
                url=url,
                summary=summary,
                author=author,
                media=media_items,
                outlet="The Quint",
                tags=tags,
                section=section,
            )
            self._fetch_article_details(article) # Hydrate the article
            articles.append(article)
        return articles

    def _fetch_article_details(self, article: Article) -> None:
        """Fetch and parse the full article content."""
        if not article.url:
            return

        # Construct the route-data.json URL
        path = article.url.replace("https://www.thequint.com", "")
        article_data_url = f"https://www.thequint.com/route-data.json?path={path}"

        resp = self.session.get(
            article_data_url,
            headers=self.HEADERS,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        if resp.status_code >= 400:
            print(f"ERROR: Failed to fetch article data {article_data_url}: {resp.status_code}")
            return

        try:
            json_data = resp.json()
            story_data = json_data.get("data", {}).get("story", {})

            # Extract content
            content_parts = []
            if "cards" in story_data:
                for card in story_data["cards"]:
                    for element in card.get("story-elements", []):
                        if element.get("type") == "text" and element.get("text"):
                            content_parts.append(element["text"])
            if content_parts:
                article.content = self._clean_html(" ".join(content_parts))

            # Update other fields if more detailed info is available
            if story_data.get("published-at"):
                try:
                    article.published_at = datetime.fromtimestamp(story_data["published-at"] / 1000).isoformat()
                except (TypeError, ValueError):
                    pass
            
            if story_data.get("author-name"):
                article.author = story_data["author-name"]

            if story_data.get("tags"):
                article.tags = [tag.get("name") for tag in story_data["tags"] if tag.get("name")]

            if story_data.get("sections") and len(story_data["sections"]) > 0:
                article.section = story_data["sections"][0].get("name")

            if story_data.get("hero-image-s3-key"):
                article.media = [MediaItem(url=f"https://media.assettype.com/{story_data['hero-image-s3-key']}", type="image")]

        except json.JSONDecodeError as e:
            print(f"Error parsing article JSON for {article.url}: {e}")


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = TheQuintScraper()
    articles = scraper.search("bangladesh", page=1, size=8)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.title}")
        print(f"  URL: {article.url}")
        if article.summary:
            print(f"  Summary: {article.summary[:100]}...")
        if article.content:
            print(f"  Content: {article.content[:500].encode('utf-8', 'ignore').decode('utf-8')}...")
        if article.author:
            print(f"  Author: {article.author}")
        if article.tags:
            print(f"  Tags: {', '.join(article.tags)}")
        if article.section:
            print(f"  Section: {article.section}")
        if article.media:
            print(f"  Media: {article.media[0].url}")
    print(f"\n{len(articles)} articles found")
