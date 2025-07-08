from __future__ import annotations

"""Hindustan Times keyword‑search scraper.

This variant cleans HTML tags/entities out of the *content* and *summary*
fields returned by the API so that downstream consumers receive plain‑text.
"""

from typing import Any, Dict, List
import html
import re

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem


class HindustanTimesScraper(BaseNewsScraper):
    """Scraper for **Hindustan Times** public search API."""

    BASE_URL = "https://api.hindustantimes.com/api/articles/search"

    DEFAULT_HEADERS: Dict[str, str] = {
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

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_html(raw: str | None) -> str | None:
        """Return *raw* stripped of HTML tags/entities ⇒ plain‑text.

        * None → None  (keeps dataclass fields None instead of "")
        * Collapses runs of whitespace to a single space and trims ends.
        """

        if not raw:
            return None
        # Decode HTML entities first so BeautifulSoup sees e.g. "₹" not "&amp;#8377;".
        raw_unescaped: str = html.unescape(raw)
        text: str = BeautifulSoup(raw_unescaped, "lxml").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None

    # ------------------------------------------------------------------
    # BaseNewsScraper mandatory overrides
    # ------------------------------------------------------------------
    def _build_params(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """Hindustan Times search endpoint accepts no query‑string params."""
        return {}

    def _build_payload(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """Render the JSON body expected by the Hindustan Times POST endpoint."""
        return {
            "searchKeyword": keyword,
            "page": str(page),
            "size": str(size),
            "type": kwargs.get("type", "story"),
        }

    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Translate Hindustan Times JSON payload → list[Article]."""

        raw_list = json_data.get("content") if json_data else []
        if not isinstance(raw_list, list):
            return []

        articles: list[Article] = []
        for item in raw_list:
            meta = item.get("metadata", {})

            # ── lead‑image handling ───────────────────────────────────────
            media_items: list[MediaItem] = []
            lead_media = item.get("leadMedia") or item.get("image")
            if lead_media and lead_media.get("image"):
                img_dict = lead_media["image"]["images"]
                # pick the highest‑res available ("original" key) → fall back to first value
                url = img_dict.get("original") or next(iter(img_dict.values()), None)
                if url:
                    media_items.append(
                        MediaItem(url=url, caption=lead_media.get("caption"), type="image")
                    )

            # ── main body paragraphs ─────────────────────────────────────
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

            # ── summary ──────────────────────────────────────────────────
            summary_raw = item.get("quickReadSummary") or item.get("summary")
            summary_clean = self._clean_html(summary_raw)

            # ── assemble Article dataclass ───────────────────────────────
            art = Article(
                title=item.get("title") or item.get("headline"),
                published_at=item.get("firstPublishedDate"),
                url=meta.get("canonicalUrl") or meta.get("url") or item.get("url"),
                content=content_body,
                summary=summary_clean,
                author=(meta.get("authors") or meta.get("author") or None),
                media=media_items,
                outlet="Hindustan Times",
                tags=[tag for tag in (meta.get("keywords") or []) if isinstance(tag, str)],
                section=meta.get("sectionName") or meta.get("section"),
            )
            articles.append(art)
        return articles


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = HindustanTimesScraper()
    arts = scraper.search("bangladesh", page=1, size=20)
    for a in arts[:3]:
        print(a.title)
        print("Summary:", a.summary)
        print("Content snippet:", (a.content or "")[:140], "…\n")
    print("Total:", len(arts))
