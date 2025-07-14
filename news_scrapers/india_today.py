from __future__ import annotations

import json

"""IndiaTodayScraper – keyword-based search scraper for *India Today*.

Supports both **search** and **article hydration**.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
import logging
import re

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem

logger = logging.getLogger(__name__)

class IndiaTodayScraper(BaseNewsScraper):
    """Scraper for **India Today** keyword search results."""

    BASE_URL = "https://www.indiatoday.in/api/ajax/loadmorecontent"
    REQUEST_METHOD = "GET"

    HEADERS: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "referer": "https://www.indiatoday.in/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    def search(
        self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any
    ) -> List[Article]:
        real_page = max(page - 1, 0)
        if size > 20:
            logger.warning("size must be ≤ 20, truncating to 20")
            size = 20
        self.PARAMS = {
            "key": keyword,
            "page": str(real_page),
            "page_type": "searchlist",
            "display": str(size),
        }
        self.PAYLOAD = {}
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, data: Dict[str, Any]) -> List[Article]:
        sections = data.get("data", {}).get("content", {})
        stories = sections.get("story", {}).get("listing", [])
        if not isinstance(stories, list):
            return []

        articles: List[Article] = []
        for item in stories:
            title = item.get("title_short")
            summary = item.get("description_short")
            url_path = item.get("canonical_url")
            full_url = urljoin("https://www.indiatoday.in", url_path) if url_path else None
            published = item.get("datetime_published")

            authors = item.get("author", [])
            author = ", ".join(a.get("title") for a in authors if a.get("title")) if authors else None

            section = None
            if cats := item.get("category_detail"):
                section = ", ".join(c.get("title") for c in cats if c.get("title"))

            media: List[MediaItem] = []
            if img_url := item.get("image_small"):
                media.append(MediaItem(url=img_url, caption=item.get("image_small_alt_text"), type="image"))

            art = Article(
                title=title,
                published_at=published,
                url=full_url,
                summary=summary,
                content=None,
                author=author,
                media=media,
                outlet="India Today",
                tags=[],
                section=section,
            )

            if full_url:
                try:
                    detail = self._fetch_article_details(full_url)
                    art.content = detail.get("content") or art.content
                    art.tags = detail.get("tags") or art.tags
                    art.author = detail.get("author") or art.author
                    art.media.extend(
                        m for m in detail.get("media", []) if m.url not in {mi.url for mi in art.media}
                    )
                except Exception:
                    logger.exception("Failed to hydrate %s", full_url)

            articles.append(art)
        return articles

    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """Hydrate full article page with content, author, tags, media."""
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        out: Dict[str, Any] = {
            "author": None,
            "content": None,
            "tags": [],
            "media": [],
        }

        # Author
        author_el = soup.select_one("a.story__author-link")
        if author_el:
            out["author"] = author_el.get_text(strip=True)

        # Content (prefer from JSON-LD)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw = script.string or ""
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("@type") == "NewsArticle":
                    out["content"] = data.get("articleBody") or out["content"]
                    break
            except Exception:
                continue

        # Fallback content from visible DOM
        if not out["content"]:
            content_root = soup.select_one("#story-left-column")
            paragraphs: List[str] = []

            if content_root:
                for node in content_root.find_all(
                        class_=lambda cls: cls and any(k in cls for k in [
                            "itg-article-first-para", "itg-article-video-text",
                            "section__content", "itg-article-para"
                        ])
                ):
                    for el in node.find_all(["p", "h2", "li"]):
                        txt = el.get_text(" ", strip=True)
                        if txt:
                            paragraphs.append(txt)
            out["content"] = "\n".join(paragraphs).strip() or None

        # First image from story-left-column
        content_root = soup.select_one("#story-left-column")
        if content_root:
            img = content_root.select_one("img[src]")
            if img and (src := img.get("src")):
                out["media"].append(MediaItem(url=src, caption=img.get("alt"), type="image"))

        # Tags
        tag_links = soup.select("div.topics ul li a")
        out["tags"] = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        return out


# ────────────────────────────── local demo ──────────────────────────────
if __name__ == "__main__":
    scraper = IndiaTodayScraper()
    results = scraper.search("bangladesh", page=1, size=20)
    for art in results:
        print(f"{art.published_at} – {art.outlet} – {art.author} – {art.title}\n{art.url}\n{art.summary}\n")
        print(f"Content: {art.content}")
        print(f"Tags: {art.tags}")
    print(f"\nTotal: {len(results)} articles.")
