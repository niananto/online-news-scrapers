from __future__ import annotations

"""ABP Live keyword-search scraper."""

import html
import re
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind


class AbpLiveScraper(BaseNewsScraper):
    """Scraper for **ABP Live** public search API."""

    BASE_URL = "https://news.abplive.com/search"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML
    
    HEADERS: Dict[str, str] = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=0, i",
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
        self, keyword: str, page: int = 1, size: int = 10, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS, then delegate to the new base `search()`."""
        if size > 18:
            print("ABP Live returns max 18 results per page – truncating from %s", size)
            size = 18

        self.PARAMS = {
            "s": keyword,
            "page": page,
        }
        return super().search(keyword, page, size, **kwargs)

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
        for item in soup.find_all("a", class_="search-newsBlk"):
            title = item.find("div", class_="story-title").get_text(strip=True) if item.find("div", class_="story-title") else None
            url = item.get("href")
            
            image_element = item.find("img")
            image_url = image_element.get("data-src") if image_element else None
            if image_url and not image_url.startswith("http"):
                image_url = f"https://news.abplive.com{image_url}"

            media_items = []
            if image_url:
                media_items.append(MediaItem(url=image_url, type="image"))

            section = item.find("div", class_="story-labels-category-name").get_text(strip=True) if item.find("div", class_="story-labels-category-name") else None

            article = Article(
                title=title,
                url=url,
                media=media_items,
                outlet="ABP Live",
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

        # Extract content from div.abp-story-article
        content_div = soup.find("div", class_="abp-story-article")
        if content_div:
            # Extract all <p> tags within the content div
            paragraphs = content_div.find_all("p")
            content_text = "\n".join([self._clean_html(str(p)) for p in paragraphs if self._clean_html(str(p))])
            article.content = content_text

        # Extract published_at from meta property
        published_time_meta = soup.find("meta", property="article:published_time")
        if published_time_meta and published_time_meta.get("content"):
            article.published_at = published_time_meta["content"]

        # Extract author
        author_element = soup.find("div", class_="abp-article-byline-author")
        if author_element:
            author_link = author_element.find("a")
            if author_link:
                article.author = author_link.get_text(strip=True)

        # Extract tags from meta keywords
        keywords_meta = soup.find("meta", attrs={'name': 'keywords'})
        if keywords_meta and keywords_meta.get("content"):
            article.tags = [tag.strip() for tag in keywords_meta["content"].split(",") if tag.strip()]

        # Extract section from meta property (fallback if not already set from search)
        if not article.section:
            section_meta = soup.find("meta", property="article:section")
            if section_meta and section_meta.get("content"):
                article.section = section_meta["content"]


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = AbpLiveScraper()
    articles = scraper.search("bangladesh", page=1, size=10)
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
