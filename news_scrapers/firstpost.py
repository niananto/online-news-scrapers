from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import logging
import html
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup  # type: ignore
import requests

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem

logger = logging.getLogger(__name__)


class FirstpostScraper(BaseNewsScraper):
    """Scraper for Firstpost keyword search (+ detail enrichment).

    This variant **cleans** the HTML returned in *body* / *app_body* so that
    downstream pipelines receive **plain‑text** only, mirroring the approach
    used in :class:`HindustanTimesScraper`.
    """

    BASE_URL = "https://api-mt.firstpost.com/nodeapi/v1/mfp/get-article-list"
    DETAIL_URL = "https://api-mt.firstpost.com/nodeapi/v1/mfp/get-article"
    REQUEST_METHOD = "GET"

    DEFAULT_HEADERS: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://www.firstpost.com",
        "referer": "https://www.firstpost.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }

    # ------------------------------------------------------------------
    # public search – limit size <= 50 (API hard‑limit)
    # ------------------------------------------------------------------
    def search(
        self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any
    ) -> List[Article]:
        if size > 50:
            logger.warning("size must be less than or equal to 50, continuing with 50…")
            size = 50
        return super().search(keyword, page, size, **kwargs)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _json_serialize(obj: Any) -> str:
        """Serialize *obj* as compact JSON (no spaces/newlines)."""
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _extract_article_id(url: str | None) -> Optional[str]:
        """Return numeric id from *weburl*, e.g. ``…-13903975.html`` → "13903975"."""
        if not url:
            return None
        m = re.search(r"-(\d+)\.html?$", url)
        return m.group(1) if m else None

    @staticmethod
    def _epoch_to_iso(epoch: int | str | None) -> Optional[str]:
        try:
            if epoch is None:
                return None
            epoch_int = int(epoch)
            return (
                datetime.fromtimestamp(epoch_int, tz=timezone.utc)
                .isoformat(sep="T", timespec="seconds")
            )
        except Exception:
            return None

    # ----------------------------- HTML → plain‑text -----------------------------
    @staticmethod
    def _clean_html(raw: str | None) -> str | None:
        """Strip *raw* HTML → plain text; collapse whitespace; decode entities."""
        if not raw:
            return None
        text = BeautifulSoup(html.unescape(raw), "lxml").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None

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
        """Construct *GET* query‑string params for the list API."""
        offset = max(page - 1, 0) * size
        filter_q = {"tags.slug": keyword.lower()}
        return {
            "count": str(size),
            "offset": str(offset),
            "fields": (
                "headline,images,display_headline,display,"  # headline/visuals
                "weburl_r,weburl,byline,intro,has_video"      # misc
            ),
            "filter": self._json_serialize(filter_q),
        }

    def _build_payload(
        self, *, keyword: str, page: int, size: int, **kwargs: Any
    ) -> Dict[str, Any]:
        """Firstpost uses *GET* only → empty payload."""
        return {}

    # ------------------------------------------------------------------
    # core response parsing
    # ------------------------------------------------------------------
    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        raw_list = json_data.get("data") if json_data else []
        if not isinstance(raw_list, list):
            return []

        articles: list[Article] = []
        for item in raw_list:
            weburl: str | None = item.get("weburl")
            article_id = self._extract_article_id(weburl)

            # Lead image (if present)
            media_items: list[MediaItem] = []
            if (img := item.get("images")) and img.get("url"):
                media_items.append(
                    MediaItem(url=img["url"], caption=img.get("caption"), type="image")
                )

            summary_clean = self._clean_html(item.get("intro"))

            art = Article(
                title=item.get("display_headline") or item.get("headline"),
                published_at=None,  # will fill after detail call
                url=weburl,
                content=None,
                summary=summary_clean,
                author=(
                    ", ".join(item.get("byline", [])) if item.get("byline") else None
                ),
                media=media_items,
                outlet="Firstpost",
                tags=[],  # will be filled from detail endpoint
                section=item.get("display") or None,
            )

            # Enrich with detail endpoint if we have an article_id.
            if article_id:
                try:
                    detail_json = self._fetch_article_details(article_id)
                    self._merge_detail(art, detail_json)
                except Exception:  # pragma: no cover – keep scraper robust
                    logger.exception("Failed to hydrate %s", weburl)

            articles.append(art)
        return articles

    # ------------------------------------------------------------------
    # detail helpers
    # ------------------------------------------------------------------
    def _fetch_article_details(self, article_id: str) -> Dict[str, Any]:
        params = {"article_id": article_id}
        resp = requests.get(
            self.DETAIL_URL, headers=self.DEFAULT_HEADERS, params=params, timeout=20
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    def _merge_detail(self, art: Article, detail: Dict[str, Any]) -> None:
        art.published_at = (
            art.published_at
            or self._epoch_to_iso(detail.get("epoch"))
            or detail.get("created_at")
        )

        # body/app_body may carry HTML or JSON – prefer *body* when available.
        body_raw = detail.get("body") or ""
        content_clean = self._clean_html(body_raw)
        if not content_clean and (app_body := detail.get("app_body")):
            # `app_body` is often a JSON string with content fragments – fallback:
            try:
                blocks = json.loads(app_body)
                if isinstance(blocks, list):
                    texts = []
                    for blk in blocks:
                        if isinstance(blk, dict):
                            txt = self._clean_html(blk.get("contentBody")) or blk.get("text")
                            if txt:
                                texts.append(txt)
                    content_clean = "\n".join(texts) if texts else None
            except Exception:
                pass
        art.content = art.content or content_clean

        art.summary = art.summary or self._clean_html(detail.get("intro"))

        # author handling – prefer detail.
        authors = detail.get("author_byline") or []
        names = [a.get("english_name") for a in authors if a.get("english_name")]
        if names:
            art.author = ", ".join(names)

        # tags/section
        tags = [t.get("name") for t in detail.get("tags", []) if t.get("name")]
        if tags:
            art.tags = tags
        art.section = (
            detail.get("section") or detail.get("categories") or art.section
        )

        # images list in detail – enrich media.
        if (img := detail.get("images")) and img.get("url") and not art.media:
            art.media.append(
                MediaItem(url=img["url"], caption=img.get("caption"), type="image")
            )


# ─────────────────── tiny sanity demo ───────────────────
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)

    scraper = FirstpostScraper()
    arts = scraper.search("bangladesh", page=1, size=50)
    for a in arts[:3]:
        print(a.published_at, "–", a.author, "-", a.title)
        print(a.url)
        print("summary:", a.summary)
        print("content snippet:", (a.content or "")[:140], "…")
        print("tags:", a.tags, "section:", a.section)
        print("media:", a.media[:1] if a.media else None)
        print()
