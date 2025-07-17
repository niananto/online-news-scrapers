from __future__ import annotations

import json

"""Times of India keyword-search scraper."""

import html
import re
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind


class TimesOfIndiaScraper(BaseNewsScraper):
    """Scraper for **Times of India** public search API."""

    BASE_URL = "https://toifeeds.indiatimes.com/treact/feeds/toi/web/show/topic"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON
    
    HEADERS: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "Referer": "https://timesofindia.indiatimes.com/",
    }

    def search(
        self, keyword: str, page: int = 1, size: int = 20, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS, then delegate to the new base `search()`."""
        if size > 20:
            print("Times of India returns max 20 results per page – truncating from %s", size)
            size = 20

        self.PARAMS = {
            "path": f"/topic/{keyword}/news",
            "row": size,
            "curpg": page,
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
        items = json_data.get("contentsData", {}).get("items", [])

        for item in items:
            title = item.get("hl")
            url = item.get("wu")
            summary = self._clean_html(item.get("syn"))
            published_at = item.get("dl")
            if published_at:
                try:
                    # Convert Unix timestamp (milliseconds) to ISO-8601 string
                    published_at = datetime.fromtimestamp(published_at / 1000).isoformat()
                except (TypeError, ValueError):
                    published_at = None
            author = item.get("ag")
            image_id = item.get("imageid")
            
            # Extract section from URL
            section = None
            if url:
                url_parts = url.split("/")
                if len(url_parts) >= 4 and url_parts[3]:
                    section = url_parts[3].replace("-", " ").title()
            
            image_url = None
            if image_id:
                # Construct image URL based on common TOI pattern
                image_url = f"https://static.toiimg.com/thumb/msid-{image_id},width-400,resizemode-4/{image_id}.jpg"

            media_items = []
            if image_url:
                media_items.append(MediaItem(url=image_url, type="image"))

            article = Article(
                title=title,
                published_at=published_at,
                url=url,
                summary=summary,
                author=author,
                media=media_items,
                outlet="Times of India",
                section=section,
            )
            self._fetch_article_details(article) # Hydrate the article
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

        # Extract content from JSON-LD
        json_ld_script = soup.find("script", type="application/ld+json")
        if json_ld_script:
            try:
                json_ld_data = json.loads(json_ld_script.string)
                # Look for NewsArticle schema and its articleBody
                if isinstance(json_ld_data, dict) and json_ld_data.get("@type") == "NewsArticle" and "articleBody" in json_ld_data:
                    article.content = self._clean_html(json_ld_data["articleBody"])
                # If not NewsArticle, check if it's a list of schemas
                elif isinstance(json_ld_data, list):
                    for schema in json_ld_data:
                        if schema.get("@type") == "NewsArticle" and "articleBody" in schema:
                            article.content = self._clean_html(schema["articleBody"])
                            break
            except json.JSONDecodeError:
                pass # Fallback to other methods if JSON-LD is malformed

        # Fallback to HTML parsing if content is still empty
        if not article.content:
            content_div = soup.find("div", class_="_s30J clearfix") or soup.find("div", class_="_s30J")
            if content_div:
                article.content = self._clean_html(str(content_div))

        # Extract tags from meta keywords
        keywords_meta = soup.find("meta", attrs={'name': 'keywords'})
        if keywords_meta and keywords_meta.get("content"):
            article.tags = [tag.strip() for tag in keywords_meta["content"].split(",") if tag.strip()]

        # Extract section from canonical URL
        canonical_link = soup.find("link", rel="canonical")
        if canonical_link and canonical_link.get("href"):
            url_parts = canonical_link["href"].split("/")
            # Section is usually the second part after the domain, e.g., /india/ or /world/
            if len(url_parts) >= 4 and url_parts[3]:
                article.section = url_parts[3].replace("-", " ").title()


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = TimesOfIndiaScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
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
