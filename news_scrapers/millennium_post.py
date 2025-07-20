from __future__ import annotations

"""Millennium Post keyword-search scraper."""

import html
import json
import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind


class MillenniumPostScraper(BaseNewsScraper):
    """Scraper for **Millennium Post** public search API."""

    BASE_URL = "https://www.millenniumpost.in/search"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML
    
    HEADERS: Dict[str, str] = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9,bn;q=0.8",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=0, i",
        "referer": "https://www.millenniumpost.in/",
        "sec-ch-ua": "\"Not)A;Brand\";v=\"8\", \"Chromium\";v=\"138\", \"Google Chrome\";v=\"138\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }

    def search(
        self, keyword: str, page: int = 1, size: int = 12, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS, then delegate to the new base `search()`."""
        if size > 12:
            print("Millennium Post returns max 12 results per page – truncating from %s", size)
            size = 12

        self.PARAMS = {
            "search": keyword,
            "search_type": "all",
            "page": page,
        }
        return super().search(keyword, page, size, **kwargs)

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

        # Try to extract data from JSON-LD
        json_ld_script = soup.find("script", type="application/ld+json")
        if json_ld_script:
            try:
                json_ld_data = json.loads(json_ld_script.string)
                if isinstance(json_ld_data, dict):
                    # Published Date
                    if "datePublished" in json_ld_data:
                        article.published_at = json_ld_data["datePublished"]
                    # Author
                    if "author" in json_ld_data and "name" in json_ld_data["author"]:
                        article.author = json_ld_data["author"]["name"]
                    # Tags
                    if "keywords" in json_ld_data:
                        article.tags = [tag.strip() for tag in json_ld_data["keywords"].split(",") if tag.strip()]
                    # Section
                    if "articleSection" in json_ld_data:
                        article.section = json_ld_data["articleSection"]
                    # Media
                    if "image" in json_ld_data and "url" in json_ld_data["image"]:
                        media_items = [MediaItem(url=json_ld_data["image"]["url"], type="image")]
                        article.media = media_items
            except json.JSONDecodeError:
                pass # Fallback to HTML parsing if JSON-LD is malformed

        # Fallback to HTML parsing if data not found in JSON-LD or for content
        # Extract content
        content_div = soup.find("div", class_="details-content-story")
        if content_div:
            article.content = self._clean_html(str(content_div))

        # Extract author (fallback)
        if not article.author:
            author_element = soup.find("div", class_="author-name")
            if author_element:
                article.author = author_element.get_text(strip=True)

        # Extract tags (fallback)
        if not article.tags:
            keywords_meta = soup.find("meta", attrs={'name': 'keywords'}) or soup.find("meta", attrs={'name': 'news_keywords'})
            if keywords_meta and keywords_meta.get("content"):
                article.tags = [tag.strip() for tag in keywords_meta["content"].split(",") if tag.strip()]

        # Extract section from URL (fallback)
        if not article.section and article.url:
            match = re.search(r'millenniumpost.in/([^/]+)/', article.url)
            if match:
                article.section = match.group(1).replace("-", " ").title()

        # Extract media (fallback)
        if not article.media:
            thumbnail_link = soup.find("link", itemprop="thumbnailUrl")
            if thumbnail_link and thumbnail_link.get("href"):
                article.media = [MediaItem(url=thumbnail_link["href"], type="image")]
            else:
                thumbnail_span = soup.find("span", itemprop="thumbnail")
                if thumbnail_span:
                    image_link = thumbnail_span.find("link", itemprop="url")
                    if image_link and image_link.get("href"):
                        article.media = [MediaItem(url=image_link["href"], type="image")]

    @staticmethod
    def _clean_html(raw: str | None) -> str | None:
        if not raw:
            return None
        raw_unescaped: str = html.unescape(raw)
        text: str = BeautifulSoup(raw_unescaped, "lxml").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None

    def _parse_response(self, html_data: str) -> List[Article]:
        """Convert the HTML response into a list of `Article` objects."""
        soup = BeautifulSoup(html_data, "lxml")
        articles: list[Article] = []
        for item in soup.find_all("div", class_="listing_item"):
            title_element = item.find("h3").find("a")
            title = title_element.get_text(strip=True)
            url = title_element.get("href") or ""
            url = "https://www.millenniumpost.in" + url
            
            image_element = item.find("img")
            image_url = image_element.get("src") if image_element else None
            if image_url and not image_url.startswith("http"):
                image_url = "https://www.millenniumpost.in" + image_url
            
            summary_element = item.find("p")
            summary = summary_element.get_text(strip=True) if summary_element else None

            published_at_element = item.find("div", class_="listing_item_date")
            published_at = published_at_element.get_text(strip=True) if published_at_element else None

            media_items = []
            if image_url:
                media_items.append(MediaItem(url=image_url, type="image"))

            article = Article(
                title=title,
                published_at=published_at,
                url=url,
                summary=summary,
                media=media_items,
                outlet="Millennium Post",
            )
            self._fetch_article_details(article) # Hydrate the article
            articles.append(article)
        return articles


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = MillenniumPostScraper()
    articles = scraper.search("bangladesh", page=1, size=12)
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
