from __future__ import annotations

"""Hindustan Times keyword-search scraper – updated for the new BaseNewsScraper."""

from typing import Any, Dict, List
import html
import re

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem


class HindustanTimesScraper(BaseNewsScraper):
    """Scraper for **Hindustan Times** public search API."""

    BASE_URL = "https://api.hindustantimes.com/api/articles/search"
    REQUEST_METHOD = "POST"
    # ← renamed to match the new base-class field
    HEADERS: Dict[str, str] = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/json",
        "origin": "https://www.hindustantimes.com",
        "referer": "https://www.hindustantimes.com/search",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    # ------------------------------------------------------------------ #
    # minimal glue for the new BaseNewsScraper                           #
    # ------------------------------------------------------------------ #
    def search(
        self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS/PAYLOAD, then delegate to the new base `search()`."""
        self.PAYLOAD = {
            "searchKeyword": keyword,
            "page": str(page),
            "size": str(size),
            "type": kwargs.get("type", "story"),
        }
        return super().search(keyword, page, size, **kwargs)

    # ------------------------------------------------------------------ #
    # helpers                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean_html(raw: str | None) -> str | None:
        if not raw:
            return None
        raw_unescaped: str = html.unescape(raw)
        text: str = BeautifulSoup(raw_unescaped, "lxml").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None

    # ------------------------------------------------------------------ #
    # unchanged JSON-to-Article parsing                                   #
    # ------------------------------------------------------------------ #
    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:  # noqa: D401
        raw_list = json_data.get("content") if json_data else []
        if not isinstance(raw_list, list):
            return []

        articles: list[Article] = []
        for item in raw_list:
            meta = item.get("metadata", {})

            # lead image
            media_items: list[MediaItem] = []
            lead_media = item.get("leadMedia") or item.get("image")
            if lead_media and lead_media.get("image"):
                img_dict = lead_media["image"]["images"]
                url = img_dict.get("original") or next(iter(img_dict.values()), None)
                if url:
                    media_items.append(
                        MediaItem(url=url, caption=lead_media.get("caption"), type="image")
                    )

            # body paragraphs
            content_body: str | None = None
            if item.get("listElement"):
                paragraphs_raw = [
                    el.get("paragraph", {}).get("body", "")
                    for el in item["listElement"]
                    if el.get("type") == "paragraph"
                ]
                paragraphs_clean = [
                    self._clean_html(p) for p in paragraphs_raw if p and self._clean_html(p)
                ]
                if paragraphs_clean:
                    content_body = "\n".join(paragraphs_clean)

            # summary
            summary_raw = item.get("quickReadSummary") or item.get("summary")
            summary_clean = self._clean_html(summary_raw)

            # assemble Article
            articles.append(
                Article(
                    title=item.get("title") or item.get("headline"),
                    published_at=item.get("firstPublishedDate"),
                    url=meta.get("canonicalUrl") or meta.get("url") or item.get("url"),
                    content=content_body,
                    summary=summary_clean,
                    author=(meta.get("authors") or meta.get("author") or None),
                    media=media_items,
                    outlet="Hindustan Times",
                    tags=[t for t in (meta.get("keywords") or []) if isinstance(t, str)],
                    section=meta.get("sectionName") or meta.get("section"),
                )
            )
        return articles


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = HindustanTimesScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
              f"{article.url}\n"
              f"Summary: {article.summary}\n"
              f"Content: {article.content[:120] if article.content else ''} ...\n"
              f"{article.media}\n"
              f"{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")
