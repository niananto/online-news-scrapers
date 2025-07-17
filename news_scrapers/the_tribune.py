from __future__ import annotations

import logging
from typing import Generator, List, Any
from bs4 import BeautifulSoup
from news_scrapers.base import Article, BaseNewsScraper, MediaItem
import json

logger = logging.getLogger(__name__)


class TheTribuneScraper(BaseNewsScraper):
    BASE_URL = "https://www.tribuneindia.com"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = "html"

    def search(self, keyword: str, page: int = 1, size: int = 10, **kwargs: Any) -> List[Article]:
        if size > 10:
            logger.warning("size must be ≤ 10, truncating to 10")
            size = 10

        self.BASE_URL = f"https://www.tribuneindia.com/topic/{keyword}?page={page}"
        self.PARAMS = {}
        self.PAYLOAD = {}

        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, html_text: str) -> List[Article]:
        soup = BeautifulSoup(html_text, "lxml")
        cards = soup.select(".post-item.search_post")

        articles = []
        for card in cards:
            try:
                a = card.select_one(".post-header a")
                if not a:
                    continue
                url = a["href"]

                title = a.get_text(strip=True)

                section = None
                cat = card.select_one(".post-cat a")
                if cat:
                    section = cat.get_text(strip=True)

                author = None
                author_tag = card.select_one(".auth-name a")
                if author_tag:
                    author = author_tag.get_text(strip=True)

                published_at = None
                time_tag = card.select_one(".post-time")
                if time_tag:
                    published_at = time_tag.get_text(strip=True)

                media = []
                img_tag = card.select_one("img.post-featured-img")
                if img_tag and img_tag.get("src"):
                    media.append(
                        MediaItem(
                            url=img_tag["src"],
                            caption=img_tag.get("alt", "").strip(),
                            type="image"
                        )
                    )

                article = Article(
                    url=url,
                    title=title,
                    author=author,
                    published_at=published_at,
                    section=section,
                    media=media,
                    outlet="The Tribune"
                )

                try:
                    hydration = self._fetch_article_details(url)
                    article.content = hydration.get("content")
                    article.summary = hydration.get("summary")
                    article.author = hydration.get("author") or article.author
                    article.published_at = hydration.get("published_at") or article.published_at
                    article.media.extend(m for m in hydration.get("media", []) if m.url not in {x.url for x in article.media})
                    article.tags = hydration.get("tags", [])
                except Exception:
                    logger.exception("Hydration failed for %s", url)

                articles.append(article)

            except Exception:
                logger.exception("Failed to parse a search card")
                continue

        return articles

    def _fetch_article_details(self, url: str) -> dict:
        resp = self.session.get(url, headers=self.HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        out = {
            "author": None,
            "published_at": None,
            "summary": None,
            "content": None,
            "media": [],
            "tags": [],
        }

        # JSON-LD backup parser
        try:
            scripts = soup.select('script[type="application/ld+json"]', limit=10)
            for script in scripts:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    out["author"] = data.get("author", {}).get("name") or out["author"]
                    out["published_at"] = data.get("datePublished") or out["published_at"]
                    out["summary"] = data.get("description") or out["summary"]
                    out["content"] = data.get("articleBody") or out["content"]
                    out["tags"].extend(data.get("keywords", [])[0] if isinstance(data.get("keywords"), list) else [])
                    img_obj = data.get("image")
                    if isinstance(img_obj, dict) and img_obj.get("url"):
                        out["media"].append(MediaItem(url=img_obj["url"], type="image"))
        except Exception:
            logger.exception("Failed to parse JSON-LD metadata")

        # fallback body parse
        try:
            paras = soup.select("#story-detail p")
            if paras:
                content = [p.get_text(strip=True) for p in paras if p.get_text(strip=True)]
                out["content"] = "\n".join(content).strip() or out["content"]
        except Exception:
            logger.exception("Failed to parse <p> content")

        return out


if __name__ == "__main__":
    scraper = TheTribuneScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
              f"{article.url}\n"
              f"Summary: {article.summary}\n"
              f"Content: {article.content[:300] if article.content else ''} ...\n"
              f"{article.media}\n"
              f"{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")
