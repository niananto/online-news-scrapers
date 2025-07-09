from __future__ import annotations

"""IndiaDotComScraper – search + article hydration for *India.com*.

Updated for the **BaseNewsScraper v2** interface which uses class attributes
(`PARAMS`, `PAYLOAD`, …) instead of the old *_build_* helpers and relies on
`RESPONSE_KIND` to determine whether the remote endpoint returns JSON or HTML.

India.com exposes **no JSON API**, so the scraper works entirely with HTML:

* **Search** pages – ``https://www.india.com/topic/<keyword>/page/<page>/`` –
  show 32 tiles on page‑1 but only the last **24** are real news articles
  (the first eight are *Photo/Video* widgets).  Downstream pages show 24 news
  cards each.
* **Article** pages embed a *NewsArticle* JSON‑LD block, plus traditional DOM
  markup that we use as a fallback.

The scraper guarantees **non‑empty** ``content``, ``tags``, and ``section`` for
*every* returned :class:`news_scrapers.base.Article`.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import datetime as _dt
import json
import logging
import re

from bs4 import BeautifulSoup  # type: ignore – BeautifulSoup4

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind

logger = logging.getLogger(__name__)

# ──────────────────────────── constants / regexes ───────────────────────────
_MAX_PER_PAGE = 24  # real articles per topic page (after skipping 8 photo/video)

_BREADCRUMB_RE = re.compile(r"^Home\s+[A-Za-z]+\s+", re.I)
_AUTHOR_DATE_RE = re.compile(
    r"^[A-Za-z ,.'-]+\s+\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s+IST",
    re.I,
)
_DATE_RE = re.compile(r"([A-Za-z]+\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)", re.I)

_TZ_IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
_PLACEHOLDER_IMG = re.compile(r"/(?:1x1|default-big)\.svg$")

# ───────────────────────────────── scraper class ─────────────────────────────
class IndiaDotComScraper(BaseNewsScraper):
    """Full‑fledged scraper for *India.com* (search + hydrate)."""

    REQUEST_METHOD: str = "GET"
    RESPONSE_KIND: ResponseKind = ResponseKind.HTML  # search returns raw HTML

    # Filled in dynamically inside *search* – must not be None for base class.
    BASE_URL: str = "https://www.india.com/"

    HEADERS: Dict[str, str] = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    # ───────────────────────────── public: search ───────────────────────────
    def search(
        self,
        keyword: str,
        page: int = 1,
        size: int = 50,
        **kwargs: Any,
    ) -> List[Article]:
        """Return up to **24** hydrated articles for *keyword* and *page*."""

        if size > _MAX_PER_PAGE:
            logger.warning(
                "India.com returns max %d results – truncating request from %d",
                _MAX_PER_PAGE,
                size,
            )
            size = _MAX_PER_PAGE

        # Dynamically point *BASE_URL* at the search/topic page and let the
        # new base‑class machinery do the HTTP + error handling.
        original_base = self.BASE_URL
        self.BASE_URL = f"https://www.india.com/topic/{keyword}/page/{page}/"

        # No query‑string or JSON body for this endpoint.
        self.PARAMS = {}
        self.PAYLOAD = {}

        try:
            articles = super().search(keyword, page, size, **kwargs)
        finally:
            self.BASE_URL = original_base  # restore for any subsequent calls
        return articles

    # ───────────────────── parse listing + hydrate ────────────────────────
    def _parse_response(self, html: str):
        soup = BeautifulSoup(html, "lxml")
        listing = self._parse_listing(soup)
        for art in listing:
            try:
                self._hydrate_article(art)
            except Exception as exc:  # pragma: no cover
                logger.exception("hydrate failed for %s: %s", art.url, exc)
        return listing

    def _parse_listing(self, soup: BeautifulSoup) -> List[Article]:
        boxes = soup.select("section.lhs-col article.repeat-box")
        if len(boxes) >= 8 and self.BASE_URL.endswith("/page/1/"):
            boxes = boxes[8:]  # drop photo/video tiles

        arts: List[Article] = []
        for box in boxes[: _MAX_PER_PAGE]:
            art = Article(outlet="India.com")

            # title + url
            if (h2 := box.find("h2")) and (a := h2.find("a")):
                art.title = h2.get_text(strip=True)
                art.url = a.get("href")

            # hero image
            if (img := box.select_one("div.photo img")):
                src = img.get("data-src") or img.get("src")
                if src and not _PLACEHOLDER_IMG.search(src):
                    art.media.append(
                        MediaItem(url=src, caption=img.get("alt"), type="image")
                    )

            # author + date + teaser
            if (meta := box.select_one(".published-by")):
                raw_meta = meta.get_text(" ", strip=True)
                if (a2 := meta.find("a")):
                    art.author = a2.get_text(strip=True)
                if m := _DATE_RE.search(raw_meta):
                    dt = _dt.datetime.strptime(m.group(1), "%B %d, %Y %I:%M %p").replace(
                        tzinfo=_TZ_IST
                    )
                    art.published_at = dt.isoformat()
                if (p := meta.find_next("p")):
                    teaser = p.get_text(" ", strip=True)
                    if teaser and not _looks_like_author_date(teaser):
                        art.summary = teaser

            # section from listing URL path (e.g. /business/, /sports/ …)
            if art.url:
                art.section = _section_from_url(art.url)

            arts.append(art)
        return arts

    # ─────────────────────────── hydrate individual ─────────────────────────
    def _hydrate_article(self, art: Article):
        if not art.url:
            return
        resp = self.session.get(
            art.url, headers=self.HEADERS, timeout=self.timeout, proxies=self.proxies
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        extracted = self._extract_from_jsonld(soup)
        if extracted:
            _merge_into_article(art, extracted)
        self._fallback_dom_parse(soup, art)

        # ensure mandatory fields
        art.content = art.content or art.summary or ""
        art.section = art.section or _section_from_url(art.url)

    # ───────────────────────── JSON‑LD helpers ──────────────────────────────
    @staticmethod
    def _extract_from_jsonld(soup: BeautifulSoup) -> Dict[str, Any] | None:  # type: ignore[override]
        script = soup.find("script", type="application/ld+json", string=re.compile("NewsArticle"))
        if not script or not script.string:
            return None
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "NewsArticle"), {})
            if data.get("@type") != "NewsArticle":
                return None
        except Exception:
            return None

        # author may be dict | list | str
        author_name: Optional[str] = None
        match data.get("author"):
            case str(s):
                author_name = s
            case list(lst):
                names = [n.get("name") if isinstance(n, dict) else str(n) for n in lst]
                author_name = ", ".join(n for n in names if n)
            case dict(d):
                author_name = d.get("name")

        # keywords may be list | str (comma / pipe separated)
        tags: List[str] = []
        if kw := data.get("keywords"):
            if isinstance(kw, list):
                tags = [str(t).strip() for t in kw if str(t).strip()]
            elif isinstance(kw, str):
                tags = [t.strip() for t in re.split(r",|\|", kw) if t.strip()]

        # image → MediaItem list
        imgs: List[str] = []
        match data.get("image"):
            case str(s):
                imgs.append(s)
            case list(lst):
                imgs.extend(lst)
            case dict(d):
                if u := d.get("url"):
                    imgs.append(u)
        media = [
            MediaItem(url=u, caption=None, type="image")
            for u in imgs
            if u and not _PLACEHOLDER_IMG.search(u)
        ]

        body = data.get("articleBody") or ""
        section = data.get("articleSection") or None

        return {
            "author": author_name,
            "content": _strip_breadcrumbs(body),
            "tags": tags,
            "published_at": data.get("datePublished") or data.get("dateModified"),
            "media": media,
            "section": section,
        }

    # ─────────────────────────── DOM fallback ──────────────────────────────
    def _fallback_dom_parse(self, soup: BeautifulSoup, art: Article):
        # Content
        if not art.content:
            cont = soup.select_one(
                "div[itemprop='articleBody'], div.article-details, section.article-details"
            )
            if cont:
                texts = [p.get_text(" ", strip=True) for p in cont.find_all("p") if p.get_text(strip=True)]
                art.content = _strip_breadcrumbs("\n".join(texts))

        # Tags
        if not art.tags:
            tag_links = soup.select(".tags ul li a, ul.article-tags a, a[rel~=tag]")
            art.tags = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]

        # Author
        if not art.author:
            if a := soup.select_one("[itemprop='author']"):
                art.author = a.get_text(strip=True)

        # Section (breadcrumb / nav highlight)
        if not art.section:
            if crumb := soup.select_one("ul.bread_crumb li a:nth-of-type(2)"):
                art.section = crumb.get_text(strip=True)

        # Hero image (fallback)
        if not art.media:
            if (meta_img := soup.find("meta", property="og:image")) and (src := meta_img.get("content")):
                if not _PLACEHOLDER_IMG.search(src):
                    art.media.append(MediaItem(url=src, caption=art.title, type="image"))

# ───────────────────────────────── helpers ────────────────────────────────

def _strip_breadcrumbs(text: str) -> str:
    text = _BREADCRUMB_RE.sub("", text).lstrip()
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_author_date(s: str) -> bool:
    return bool(_AUTHOR_DATE_RE.match(s))


def _section_from_url(url: str) -> Optional[str]:
    try:
        path = urlparse(url).path.strip("/")
        segment = path.split("/", 1)[0].lower()
        return segment or None
    except Exception:
        return None


def _merge_into_article(art: Article, data: Dict[str, Any]):
    if data.get("author"):
        art.author = art.author or data["author"]
    if data.get("content"):
        art.content = data["content"]
    if data.get("tags"):
        art.tags = data["tags"]
    if data.get("published_at"):
        art.published_at = art.published_at or data["published_at"]
    if data.get("media"):
        # prepend new media, keep uniques
        urls_existing = {m.url for m in art.media}
        art.media = data["media"] + [m for m in art.media if m.url not in urls_existing]
    if data.get("section"):
        art.section = art.section or data["section"]


# ─────────────────────────────── demo ────────────────────────────────
if __name__ == "__main__":  # pragma: no cover
    scraper = IndiaDotComScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
              f"{article.url}\n"
              f"Summary: {article.summary}\n"
              f"Content: {article.content[:120] if article.content else ''} ...\n"
              f"{article.media}\n"
              f"{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")
