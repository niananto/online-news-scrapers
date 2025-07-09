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


class BusinessStandardScraper(BaseNewsScraper):
    """Scraper for **Business Standard** search + article pages."""

    BASE_URL = "https://apibs.business-standard.com/search/"
    REQUEST_METHOD = "GET"

    HEADERS: Dict[str, str] = {
        "accept": "application/json",
        "origin": "https://www.business-standard.com",
        "referer": "https://www.business-standard.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    IMG_PREFIX = "https://bsmedia.business-standard.com"
    URL_PREFIX = "https://www.business-standard.com"

    # ─────────────────── new-style entry-point ───────────────────
    def search(
        self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any
    ) -> List[Article]:
        self.PARAMS = {
            "type": kwargs.get("type", "news"),
            "limit": str(size),
            "page": str(page),
            "keyword": keyword,
        }
        self.PAYLOAD = {}  # GET-only
        return super().search(keyword, page, size, **kwargs)

    # ─────────────────── response parsing (unchanged) ───────────────────
    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        raw_list: Sequence[Dict[str, Any]] = (
            json_data.get("data", {}).get("news", []) if json_data else []
        )
        if not isinstance(raw_list, list):
            return []

        articles: List[Article] = []
        for item in raw_list:
            url_path = item.get("article_url")
            full_url = urljoin(self.URL_PREFIX, url_path) if url_path else None

            img_path = item.get("image_path")
            img_url = urljoin(self.IMG_PREFIX, img_path) if img_path else None
            media = [MediaItem(url=img_url, type="image")] if img_url else []

            section = (
                url_path.split("/", 2)[1]
                if url_path and url_path.startswith("/") and "/" in url_path[1:]
                else None
            )

            art = Article(
                title=item.get("heading1"),
                published_at=item.get("published_date"),
                url=full_url,
                summary=item.get("sub_heading"),
                media=media,
                outlet="Business Standard",
                section=section,
            )

            if full_url:  # hydrate from article page
                try:
                    detail = self._fetch_article_details(full_url)
                except Exception:  # pragma: no cover
                    logger.exception("hydrate failed for %s", full_url)
                    detail = {}

                art.author = detail.get("author") or art.author
                art.content = detail.get("content") or art.content
                art.tags = detail.get("tags", art.tags)
                art.published_at = detail.get("published_at") or art.published_at
                extra = detail.get("media", [])
                art.media.extend(m for m in extra if m.url not in {x.url for x in art.media})

            articles.append(art)
        return articles

    # ─────────────────── detail helpers (headers updated) ───────────────────
    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        detail = {
            "author": None,
            "content": None,
            "tags": [],
            "published_at": None,
            "media": [],
        }

        ld = self._find_newsarticle_ldjson(soup)
        if ld:
            detail.update(ld)
        self._fallback_dom_parse(soup, detail)
        return detail

    # ──────────────────────────── JSON‑LD parsing ──────────────────────────────
    @staticmethod
    def _find_newsarticle_ldjson(soup: BeautifulSoup) -> Dict[str, Any] | None:
        """Locate the *NewsArticle* JSON‑LD and convert it into our internal dict."""
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or ""
            try:
                data = json.loads(html.unescape(raw))
            except json.JSONDecodeError:
                continue

            # Schema might be an *array* or a single dict – walk recursively.
            queue: List[Any] = [data]
            while queue:
                node = queue.pop()
                if isinstance(node, dict):
                    if node.get("@type") == "NewsArticle":
                        return BusinessStandardScraper._extract_from_jsonld(node)
                    queue.extend(node.values())  # breadth‑search nested dicts/lists
                elif isinstance(node, list):
                    queue.extend(node)
        return None

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _extract_from_jsonld(node: Dict[str, Any]) -> Dict[str, Any]:
        """Map the *NewsArticle* schema keys onto our internal Article fields."""
        author_field = node.get("author", []) or []
        if isinstance(author_field, dict):
            author_field = [author_field]
        author_name = ", ".join(
            a.get("name") for a in author_field if isinstance(a, dict) and a.get("name")
        ) or None

        # *image* may be str | list[str] | {"url": str}
        imgs: List[str] = []
        match node.get("image"):
            case str(s):
                imgs.append(s)
            case list(lst):
                imgs.extend(lst)
            case dict(d):
                if (u := d.get("url")):
                    imgs.append(u)

        media_items = [MediaItem(url=i, caption=None, type="image") for i in imgs if i]

        tags = []
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
        """Populate *out* with best‑effort DOM selectors when JSON‑LD is absent."""
        # Author
        author_el = soup.select_one('[itemprop="author"], .author_name, .author')
        if author_el and not out.get("author"):
            out["author"] = author_el.get_text(strip=True)

        # Body text
        if not out.get("content"):
            body_el = soup.select_one('[itemprop="articleBody"], .story-content, .artibody, .p-content')
            if body_el:
                paragraphs = body_el.find_all(["p", "h2", "li"]) or [body_el]
                text = "\n".join(p.get_text(" ", strip=True) for p in paragraphs)
                out["content"] = re.sub(r"\n{2,}", "\n", text).strip()

        # Tags / keywords
        if not out.get("tags"):
            tag_links = soup.select(".tags li a, a[rel~=tag], .topic-tags a")
            out["tags"] = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        # Images inside the story wrapper (first <img> as hero)
        if not out.get("media"):
            img_el = soup.select_one("article img, .story img, .artibody img")
            if img_el and (src := img_el.get("src")):
                out["media"] = [MediaItem(url=src, caption=img_el.get("alt"), type="image")]


# ────────────────────────────── tiny demo ───────────────────────────────
if __name__ == "__main__":
    scraper = BusinessStandardScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
              f"{article.url}\n"
              f"Summary: {article.summary}\n"
              f"Content: {article.content[:120] if article.content else ''} ...\n"
              f"{article.media}\n"
              f"{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")
