from __future__ import annotations

from typing import Any, Dict, List, Sequence
from urllib.parse import urljoin
import html
import json
import re
import logging

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem

logger = logging.getLogger(__name__)


class BusinessStandardScraper(BaseNewsScraper):
    """Scraper for **Business‑Standard** search + article pages."""

    BASE_URL: str = "https://apibs.business-standard.com/search/"
    REQUEST_METHOD: str = "GET"  # the base‑class will send GET instead of POST

    DEFAULT_HEADERS: Dict[str, str] = {
        "accept": "application/json",
        "origin": "https://www.business-standard.com",
        "referer": "https://www.business-standard.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }

    IMG_PREFIX: str = "https://bsmedia.business-standard.com"  # image_path is relative
    URL_PREFIX: str = "https://www.business-standard.com"      # article_url is relative

    def _build_params(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """Return the *query‑string* dictionary for the search request."""
        return {
            "type": kwargs.get("type", "news"),
            "limit": str(size),
            "page": str(page),
            "keyword": keyword,
        }

    def _build_payload(self, *, keyword: str, page: int, size: int, **_kwargs: Any) -> Dict[str, Any]:
        """Business‑Standard uses *GET* so no request body is necessary."""
        return {}

    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Translate the search‑API JSON into a list of :class:`Article` objects."""
        raw_list: Sequence[Dict[str, Any]] = json_data.get("data", {}).get("news", []) if json_data else []
        if not isinstance(raw_list, list):
            return []

        articles: List[Article] = []
        for item in raw_list:
            # Build canonical URLs
            url_path: str | None = item.get("article_url")
            full_url: str | None = urljoin(self.URL_PREFIX, url_path) if url_path else None

            img_path: str | None = item.get("image_path")
            full_img: str | None = urljoin(self.IMG_PREFIX, img_path) if img_path else None
            media_items: List[MediaItem] = [MediaItem(url=full_img, caption=None, type="image")] if full_img else []

            # Epoch seconds –> ISO8601 handled by dataclass post‑processing
            published_raw: int | str | None = item.get("published_date")

            # Derive *section* from the first path segment of ``article_url``.
            section: str | None = None
            if url_path and url_path.startswith("/"):
                _, first_segment, *_ = url_path.split("/", 2)  # eg "/companies/news/..." → "companies"
                section = first_segment or None

            # ── light Article object from search result ──
            art = Article(
                title=item.get("heading1"),
                published_at=published_raw,  # type: ignore[arg-type]
                url=full_url,
                content=None,  # hydrated below
                summary=item.get("sub_heading"),
                author=None,
                media=media_items,
                outlet="Business Standard",
                tags=[],
                section=section,
            )

            # ── hydrate with details from the article HTML ──
            if full_url:
                try:
                    details = self._fetch_article_details(full_url)
                except Exception:  # pragma: no cover – do *not* abort entire scrape
                    logger.exception("Failed to hydrate %s", full_url)
                    details = {}

                if details:
                    # The dataclass is *not* frozen → we can assign freely.
                    art.author = details.get("author") or art.author
                    art.content = details.get("content") or art.content
                    art.tags = details.get("tags", art.tags)
                    art.published_at = details.get("published_at") or art.published_at
                    # Merge any extra media discovered inside the article body
                    extra_media: List[MediaItem] = details.get("media", [])
                    art.media.extend(m for m in extra_media if m.url not in {mi.url for mi in art.media})

            articles.append(art)
        return articles

    # ───────────────────────────── helper: article HTML ─────────────────────────
    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """GET the article page and extract richer metadata.

        Preference order:
        1. Embedded *NewsArticle* JSON‑LD (Schema.org).
        2. DOM fall‑backs for author, body, and tags.
        """
        resp = self.session.get(url, headers=self.DEFAULT_HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        details: Dict[str, Any] = {
            "author": None,
            "content": None,
            "tags": [],
            "published_at": None,
            "media": [],
        }

        # ── 1) JSON‑LD (preferred) ────────────────────────────────────────────
        json_ld_block = self._find_newsarticle_ldjson(soup)
        if json_ld_block:
            details.update(json_ld_block)
        else:
            # ── 2) Fallback to DOM parsing ────────────────────────────────────
            self._fallback_dom_parse(soup, details)

        return details

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
    import itertools as _it

    scraper = BusinessStandardScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for art in _it.islice(articles, 5):
        print("\n==>", art.title)
        print("URL:", art.url)
        print("Date:", art.published_at)
        print("Author:", art.author)
        print("Tags:", art.tags)
        print("Media:", art.media[:2])
        if art.content:
            print("Content snippet:", art.content[:150], "…")
    print(f"Total fetched: {len(articles)}")
