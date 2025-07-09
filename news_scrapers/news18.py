from __future__ import annotations

from typing import Any, Dict, List, Sequence
from urllib.parse import urljoin
import html
import json
import logging
import re

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem

logger = logging.getLogger(__name__)


class News18Scraper(BaseNewsScraper):
    """Scraper for **News18.com** search & article pages."""

    BASE_URL = "https://api-en.news18.com/nodeapi/v1/eng/get-article-list"
    REQUEST_METHOD = "GET"

    HEADERS: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://www.news18.com",
        "referer": "https://www.news18.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    # ─────────────────── new-style entry-point ───────────────────
    def search(
        self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any
    ) -> List[Article]:
        if size > 50:
            logger.warning("size must be ≤ 50, truncating to 50")
            size = 50

        offset = max(page - 1, 0) * size
        search_fields = (
            "headline,created_at,categories,images,display_headline,weburl,weburl_r"
        )

        self.PARAMS = {
            "count": str(size),
            "offset": str(offset),
            "fields": kwargs.get("fields", search_fields),
            "filter": json.dumps({"global_search": keyword}, separators=(",", ":")),
        }
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Translate the search‑API JSON into :class:`Article` objects."""
        raw_list: Sequence[Dict[str, Any]] = json_data.get("data", []) if isinstance(json_data, dict) else []
        if not isinstance(raw_list, list):
            return []

        articles: List[Article] = []
        for item in raw_list:
            # Title – prefer *display_headline* over bare *headline*.
            title: str | None = item.get("display_headline") or item.get("headline")

            # Canonical URL.
            url: str | None = item.get("weburl")
            if not url:
                url_r: str | None = item.get("weburl_r")
                url = urljoin("https://www.news18.com", url_r) if url_r else None

            # Hero image (first of several formats, if present).
            img_url: str | None = None
            if (img := item.get("images", {})) and isinstance(img, dict):
                img_url = img.get("url")
            media: List[MediaItem] = [MediaItem(url=img_url, caption=img.get("caption"), type="image")] if img_url else []

            # Published timestamp (string *YYYY-MM-DD HH:MM:SS* in IST).
            published_raw: str | None = item.get("created_at")

            # Section – derive from first category slug, if available.
            section: str | None = None
            if (cats := item.get("categories")) and isinstance(cats, list):
                for c in cats:
                    if isinstance(c, dict) and c.get("slug"):
                        section = str(c["slug"])
                        break

            # ── create thin Article ──
            art = Article(
                title=title,
                published_at=published_raw,  # type: ignore[arg-type]
                url=url,
                content=None,
                summary=None,
                author=None,
                media=media,
                outlet="News18",
                tags=[],
                section=section,
            )

            # ── hydrate with article page ──
            if url:
                try:
                    details = self._fetch_article_details(url)
                except Exception:
                    logger.exception("Failed to hydrate %%s", url)
                    details = {}

                if details:
                    art.author = details.get("author") or art.author
                    art.content = details.get("content") or art.content
                    art.tags = details.get("tags", art.tags)
                    art.published_at = details.get("published_at") or art.published_at
                    extra_media: List[MediaItem] = details.get("media", [])
                    art.media.extend(m for m in extra_media if m.url not in {mi.url for mi in art.media})

            articles.append(art)
        return articles

    # helper: article hydration
    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """GET the article HTML and extract richer metadata.

        **Preference order**:
        1. Embedded *NewsArticle* JSON‑LD (Schema.org).
        2. DOM fall‑backs for author, body, and tags.
        """
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        details: Dict[str, Any] = {
            "author": None,
            "content": None,
            "tags": [],
            "published_at": None,
            "media": [],
        }

        # 1) JSON‑LD
        if (block := self._find_newsarticle_ldjson(soup)):
            details.update(block)
        else:
            # 2) Fallback selectors
            self._fallback_dom_parse(soup, details)

        return details

    @staticmethod
    def _find_newsarticle_ldjson(soup: BeautifulSoup) -> Dict[str, Any] | None:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or ""
            try:
                data = json.loads(html.unescape(raw))
            except json.JSONDecodeError:
                continue

            queue: List[Any] = [data]
            while queue:
                node = queue.pop()
                if isinstance(node, dict):
                    if node.get("@type") == "NewsArticle":
                        return News18Scraper._extract_from_jsonld(node)
                    queue.extend(node.values())
                elif isinstance(node, list):
                    queue.extend(node)
        return None

    @staticmethod
    def _extract_from_jsonld(node: Dict[str, Any]) -> Dict[str, Any]:
        """Map *NewsArticle* schema onto our internal structure."""
        # ── Author(s) ──
        author_field = node.get("author", []) or []
        if isinstance(author_field, dict):
            author_field = [author_field]
        author_name = ", ".join(
            a.get("name") for a in author_field if isinstance(a, dict) and a.get("name")
        ) or None

        # ── Images ──
        imgs: List[str] = []
        match node.get("image"):
            case str(s):
                imgs.append(s)
            case list(lst):
                imgs.extend(lst)
            case dict(d):
                if (u := d.get("url")):
                    imgs.append(u)
        media_items = [MediaItem(url=u, caption=None, type="image") for u in imgs if u]

        # ── Tags ──
        tags: List[str] = []
        if (kw := node.get("keywords")):
            if isinstance(kw, str):
                tags = [t.strip() for t in re.split(r",|\|", kw) if t.strip()]
            elif isinstance(kw, list):
                tags = [str(t).strip() for t in kw if str(t).strip()]

        return {
            "author": author_name,
            "content": node.get("articleBody"),
            "tags": tags,
            "published_at": node.get("datePublished") or node.get("dateModified"),
            "media": media_items,
        }

    @staticmethod
    def _fallback_dom_parse(soup: BeautifulSoup, out: Dict[str, Any]) -> None:
        # Author
        if not out.get("author"):
            author_el = soup.select_one('[itemprop="author"], .author_name, .author, .byline')
            if author_el:
                out["author"] = author_el.get_text(strip=True)

        # Body text
        if not out.get("content"):
            body_el = soup.select_one('[itemprop="articleBody"], .story-content, article')
            if body_el:
                paragraphs = body_el.find_all(["p", "h2", "li"]) or [body_el]
                text = "\n".join(p.get_text(" ", strip=True) for p in paragraphs)
                out["content"] = re.sub(r"\n{2,}", "\n", text).strip()

        # Tags
        if not out.get("tags"):
            tag_links = soup.select(".tags li a, a[rel~=tag], .topic-tags a")
            out["tags"] = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        # Inline hero image
        if not out.get("media"):
            img_el = soup.select_one("article img, .story img")
            if img_el and (src := img_el.get("src")):
                out["media"] = [MediaItem(url=src, caption=img_el.get("alt"), type="image")]


# ───────────────────────────────── demo ──────────────────────────────────
if __name__ == "__main__":
    scraper = News18Scraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
              f"{article.url}\n"
              f"Summary: {article.summary}\n"
              f"Content: {article.content[:120] if article.content else ''} ...\n"
              f"{article.media}\n"
              f"{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")
