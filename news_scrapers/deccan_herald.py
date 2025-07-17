from __future__ import annotations

import json

"""Deccan Herald keyword-search scraper."""

import html
import re
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind


class DeccanHeraldScraper(BaseNewsScraper):
    """Scraper for **Deccan Herald** public search API."""

    BASE_URL = "https://www.deccanherald.com/api/v1/advanced-search"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON
    
    HEADERS: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": "https://www.deccanherald.com/search?q=bangladesh",
        "sec-ch-ua": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Google Chrome\";v=\"138\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }

    def search(
        self, keyword: str, page: int = 1, size: int = 20, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS, then delegate to the new base `search()`."""
        self.PARAMS = {
            "sort": "latest-published",
            "q": keyword,
            "type": "text",
            "page": page,
            "size": size, # Although not in sample, common for search APIs
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
            url = f"https://www.deccanherald.com/{item.get("slug")}"
            summary = item.get("subheadline")
            published_at = item.get("published-at")
            if published_at:
                try:
                    # Convert Unix timestamp (milliseconds) to ISO-8601 string
                    published_at = datetime.fromtimestamp(published_at / 1000).isoformat()
                except (TypeError, ValueError):
                    published_at = None
            author = item.get("author-name")
            
            # Extract image
            image_url = None
            if item.get("hero-image-s3-key"):
                image_url = f"https://media.assettype.com/{item.get("hero-image-s3-key")}"

            media_items = []
            if image_url:
                media_items.append(MediaItem(url=image_url, type="image"))

            # Extract tags
            tags = []
            if item.get("tags"):
                tags = [tag.get("name") for tag in item["tags"] if tag.get("name")]

            # Extract section
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
                outlet="Deccan Herald",
                tags=tags,
                section=section,
            )
            self._fetch_article_details(article)
            articles.append(article)
        return articles

    def _fetch_article_details(self, article: Article) -> None:
        """Fetch and parse the full article content."""
        if not article.url:
            return

        resp = self.session.get(
            article.url,
            headers=self.HEADERS,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        if resp.status_code >= 400:
            print(f"ERROR: Failed to fetch article {article.url}: {resp.status_code}")
            return

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract content from story-elements in JSON-LD
        json_ld_script = soup.find("script", type="application/json", id="static-page")
        if json_ld_script:
            try:
                json_data = json.loads(json_ld_script.string)
                story_elements = json_data.get("qt", {}).get("data", {}).get("story", {}).get("cards", [{}])[0].get("story-elements", [])
                content_parts = []
                for element in story_elements:
                    if element.get("type") == "text" and element.get("text"):
                        content_parts.append(element["text"])
                if content_parts:
                    article.content = self._clean_html(" ".join(content_parts))
            except Exception as e:
                print(f"Error parsing JSON-LD for content: {e}")


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = DeccanHeraldScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.title}")
        print(f"  URL: {article.url}")
        if article.summary:
            print(f"  Summary: {article.summary[:100]}...")
        if article.content:
            print(f"  Content: {article.content[:500]}...")
        if article.author:
            print(f"  Author: {article.author}")
        if article.tags:
            print(f"  Tags: {', '.join(article.tags)}")
        if article.section:
            print(f"  Section: {article.section}")
        if article.media:
            print(f"  Media: {article.media[0].url}")
    print(f"\n{len(articles)} articles found")
