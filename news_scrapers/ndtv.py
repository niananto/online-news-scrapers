from __future__ import annotations

import logging
from typing import Any, Dict, List
from urllib.parse import urljoin
import re
from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem

logger = logging.getLogger(__name__)


class NdtvScraper(BaseNewsScraper):
    """Scraper for **NDTV** keyword search (no hydration yet)."""

    BASE_URL = "https://www.ndtv.com/topic-load-more/from/allnews/type/news/page/1/query/"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = "html"

    HEADERS: Dict[str, str] = {
        "accept": "text/html, */*; q=0.01",
        "referer": "https://www.ndtv.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "x-requested-with": "XMLHttpRequest",
    }

    # ─────────────────── entry-point ───────────────────
    def search(self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any) -> List[Article]:
        if size > 15:
            logger.warning("size must be ≤ 15, truncating to 15")
            size = 15

        self.BASE_URL = f"https://www.ndtv.com/topic-load-more/from/allnews/type/news/page/{page}/query/{keyword}"
        self.PARAMS = {}
        self.PAYLOAD = {}

        return super().search(keyword, page, size, **kwargs)

    # ─────────────────── parser ────────────────────────
    def _parse_response(self, html_text: str) -> List[Article]:
        soup = BeautifulSoup(html_text, "lxml")
        cards = soup.select("li.SrchLstPg-a-li")
        articles: list[Article] = []

        for li in cards:
            try:
                anchor = li.select_one("a.SrchLstPg_ttl")
                title = anchor.text.strip() if anchor else None
                url = anchor["href"] if anchor and anchor.has_attr("href") else None

                summary = li.select_one("p.SrchLstPg_txt")
                summary_text = summary.text.strip() if summary else None

                date_author_info = li.select("ul.pst-by_ul li")
                published_at = (
                    date_author_info[0].text.strip() if len(date_author_info) >= 1 else None
                )
                section_author = (
                    date_author_info[1].text.strip() if len(date_author_info) >= 2 else ""
                )

                # Extract section and author separately
                section, author = None, None
                match = re.match(r"(.+?)\s*\|\s*(.+)", section_author)
                if match:
                    section, author = match.groups()

                img = li.select_one("img.SrchLstPg_img-full")
                img_url = img["data-src"] if img and img.has_attr("data-src") else None
                media = [MediaItem(url=img_url, type="image")] if img_url else []

                art = Article(
                    title=title,
                    published_at=published_at,
                    url=url,
                    content=None,
                    summary=summary_text,
                    author=author,
                    media=media,
                    outlet="NDTV",
                    tags=[],
                    section=section,
                )
                if url:
                    try:
                        detail = self._fetch_article_details(url)
                        art.author = detail.get("author") or art.author
                        art.content = detail.get("content") or art.content
                        art.published_at = detail.get("published_at") or art.published_at
                        extra_media = detail.get("media", [])
                        art.media.extend(m for m in extra_media if m.url not in {x.url for x in art.media})
                    except Exception:
                        logger.exception("hydrate failed for %s", url)

                articles.append(art)

            except Exception:
                logger.exception("Failed to parse an article card")
                continue

        return articles

    def _fetch_article_details(self, url: str) -> dict:
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        out = {
            "author": None,
            "content": None,
            "published_at": None,
            "media": [],
        }

        # Author (edited by)
        edited = soup.select_one("nav.pst-by li:contains('Edited by:')")
        if edited and (a := edited.select_one("a")):
            out["author"] = a.get_text(strip=True)

        # Published date
        date_meta = soup.select_one("meta[itemprop='datePublished']")
        if date_meta and (date_val := date_meta.get("content")):
            out["published_at"] = date_val.strip()

        # Main image
        img = soup.select_one("#story_image_main")
        if img and img.get("src"):
            out["media"].append(
                MediaItem(url=img["src"], caption=img.get("alt"), type="image")
            )

        # Story body
        article_div = soup.select_one("div.sp_txt")
        if article_div:
            blocks = article_div.select("p, h3, h2, li")
            text_parts = [
                blk.get_text(" ", strip=True)
                for blk in blocks
                if blk.get_text(strip=True)
            ]
            out["content"] = "\n".join(text_parts).strip()

        return out


if __name__ == "__main__":
    scraper = NdtvScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
              f"{article.url}\n"
              f"Summary: {article.summary}\n"
              f"Content: {article.content[:300] if article.content else ''} ...\n"
              f"{article.media}\n"
              f"{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")
