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


class RepublicWorldScraper(BaseNewsScraper):
    """Scraper for **Republic World** elastic‑search API + article pages."""

    BASE_URL: str = (
        "https://public-api-dot-republic-world-prod.el.r.appspot.com/api/search/es"
    )
    REQUEST_METHOD: str = "GET"  # GET – no request body

    DEFAULT_HEADERS: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://www.republicworld.com",
        "referer": "https://www.republicworld.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        # The site expects two custom headers present in the sample *curl*.
        "lang": "E",
        "platform": "WEB",
    }

    IMG_PREFIX: str = "https://img.republicworld.com/"  # prepend to *filePath*
    URL_PREFIX: str = "https://www.republicworld.com/"  # prepend to *completeSlug*

    # ------------------------------------------------------------------
    # BaseNewsScraper mandatory overrides
    # ------------------------------------------------------------------
    def _build_params(
        self,
        *,
        keyword: str,
        page: int,
        size: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Return the query‑string dict expected by Republic World."""
        return {
            "search": keyword,
            "pageSize": str(size),
            "page": str(page),
            "searchType": kwargs.get("searchType", "ARTICLE"),
        }

    def _build_payload(
        self, *, keyword: str, page: int, size: int, **_kwargs: Any
    ) -> Dict[str, Any]:
        """The API is *GET* only – no JSON body sent."""
        return {}

    # ------------------------------------------------------------------
    # core JSON‑response parsing
    # ------------------------------------------------------------------
    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Translate the search‑API JSON into :class:`Article` objects."""
        raw_list: Sequence[Dict[str, Any]] = (
            json_data.get("data", {}).get("data", {}).get("data", []) if json_data else []
        )
        if not isinstance(raw_list, list):
            return []

        articles: List[Article] = []
        for item in raw_list:
            # ── build canonical URL ────────────────────────────────────────
            comp_slug: str | None = item.get("completeSlug") or item.get("slug")
            full_url: str | None = (
                urljoin(self.URL_PREFIX, comp_slug) if comp_slug else None
            )

            # ── hero image extraction (first available *version*) ──────────
            media_items: List[MediaItem] = []
            if (img := item.get("images", {})) and isinstance(img, dict):
                versions = img.get("versions", {})
                if isinstance(versions, dict):
                    # pick the first *filePath* available
                    for v in versions.values():
                        if isinstance(v, dict) and v.get("filePath"):
                            fp = v["filePath"].lstrip("/")
                            media_items.append(
                                MediaItem(
                                    url=urljoin(self.IMG_PREFIX, fp),
                                    caption=v.get("caption"),
                                    type="image",
                                )
                            )
                            break

            # ── basic Article instance from thin search payload ────────────
            art = Article(
                title=item.get("mid_heading"),
                published_at=item.get("createdAt") or item.get("updatedAt"),
                url=full_url,
                content=None,  # will hydrate from article page
                summary=item.get("long_heading"),
                author=None,  # not present in thin payload
                media=media_items,
                outlet="Republic World",
                tags=[],
                section=(item.get("category_id", {}) or {}).get("slug")
                or (item.get("category_id", {}) or {}).get("name"),
            )

            # ── enrich via article HTML if URL available ───────────────────
            if full_url:
                try:
                    details = self._fetch_article_details(full_url)
                except Exception:  # pragma: no cover – keep scraper robust
                    logger.exception("Failed to hydrate %%s", full_url)
                    details = {}

                if details:
                    # Prefer freshly‑scraped values but do not overwrite truthy ones.
                    art.author = details.get("author") or art.author
                    art.content = details.get("content") or art.content
                    art.tags = details.get("tags") or art.tags
                    art.published_at = details.get("published_at") or art.published_at

                    # extend media (avoid duplicates by URL)
                    extra_media: List[MediaItem] = details.get("media", [])
                    art.media.extend(
                        m for m in extra_media if m.url not in {mi.url for mi in art.media}
                    )

            articles.append(art)
        return articles

    # ------------------------------------------------------------------
    # helper: article hydration
    # ------------------------------------------------------------------
    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """GET the article HTML and extract rich metadata.

        **Preference order**:
        1. Embedded *NewsArticle* JSON‑LD (Schema.org)
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

        # 1) JSON‑LD – preferred (may still be partial)
        ld_block = self._find_newsarticle_ldjson(soup)
        if ld_block:
            details.update({k: v for k, v in ld_block.items() if v})

        # 2) Fallback selectors – always run to patch any gaps
        self._fallback_dom_parse(soup, details)

        return details

    # ------------------------------------------------------------------
    # JSON‑LD helpers (adapted from *News18Scraper*)
    # ------------------------------------------------------------------
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
                        return RepublicWorldScraper._extract_from_jsonld(node)
                    queue.extend(node.values())
                elif isinstance(node, list):
                    queue.extend(node)
        return None

    @staticmethod
    def _extract_from_jsonld(node: Dict[str, Any]) -> Dict[str, Any]:
        """Map the *NewsArticle* schema onto our internal structure."""
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

    # ------------------------------------------------------------------
    # DOM fallback helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fallback_dom_parse(soup: BeautifulSoup, out: Dict[str, Any]) -> None:
        """Populate *out* with best‑effort CSS selectors when JSON‑LD is absent or partial."""
        # Author
        if not out.get("author"):
            author_el = soup.select_one(
                '.storyByLine, .author_name, [itemprop="author"], .byline, span.byline'
            )
            if author_el:
                out["author"] = author_el.get_text(strip=True)

        # Body text
        if not out.get("content"):
            body_el = soup.select_one(
                '[itemprop="articleBody"], '
                'article, '
                '.storyText, '
                '.article-page, '
                '.storyContent, '
                '.story-page-content'
            )
            if body_el:
                # remove scripts / ads
                for tag in body_el.find_all(["script", "style", "noscript"]):
                    tag.decompose()
                paragraphs = body_el.find_all(["p", "h2", "li"]) or [body_el]
                text = "\n".join(p.get_text(" ", strip=True) for p in paragraphs)
                out["content"] = re.sub(r"\n{2,}", "\n", text).strip()

        # Tags
        if not out.get("tags"):
            tag_links = soup.select('.tags li a, a[rel~=tag], .topic-tags a, .tagsWrapper a')
            out["tags"] = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        # Inline hero image (if still missing)
        if not out.get("media"):
            img_el = soup.select_one("article img, .story img, .article-page img, .storyContent img")
            if img_el and (src := img_el.get("src")):
                out["media"] = [MediaItem(url=src, caption=img_el.get("alt"), type="image")]


# ─────────────────── tiny sanity demo ───────────────────
if __name__ == "__main__":  # pragma: no cover – manual testing only
    scraper = RepublicWorldScraper()
    arts = scraper.search("bangladesh", page=1, size=51)
    for art in arts:
        print("\n=>", art.title)
        print("URL:", art.url)
        print("Date:", art.published_at)
        print("Author:", art.author)
        print("Section:", art.section)
        print("Tags:", art.tags[:5])
        print("Media:", art.media[:1])
        if art.content:
            print("Snippet:", art.content[:120], "…")
    print(f"Total fetched: {len(arts)}")
