import json
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind


class TheGuardianScraper(BaseNewsScraper):
    """Scraper for **The Guardian** search pages."""

    BASE_URL = "https://www.theguardian.com/world/{keyword}"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML

    HEADERS: Dict[str, str] = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=0, i",
        "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }

    def search(
        self, keyword: str, page: int = 1, size: int = 10, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS, then delegate to the new base `search()`."""
        self.BASE_URL = self.BASE_URL.format(keyword=keyword)
        self.PARAMS = {
            "page": page,
        }
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, html_data: str) -> List[Article]:
        """Convert the HTML response into a list of `Article` objects."""
        soup = BeautifulSoup(html_data, "lxml")
        articles: list[Article] = []
        # Find all links and filter them based on their href
        all_links = soup.find_all("a")
        article_links = [
            link
            for link in all_links
            if link.has_attr("href")
            and re.search(r"/\w+/\d{4}/\w+/\d{2}/", link["href"])
        ]

        for link in article_links:
            title = link.get_text(strip=True)
            url = link.get("href")
            if not url.startswith("http"):
                url = urljoin("https://www.theguardian.com", url)

            media_items = []
            parent_container = link.find_parent("div", class_="fc-item__container")
            if parent_container:
                image_element = parent_container.find("img")
                if image_element:
                    image_url = image_element.get("src")
                    if image_url:
                        media_items.append(MediaItem(url=image_url, type="image"))

            section = None
            try:
                section = url.split("/")[3]
            except IndexError:
                pass

            article = Article(
                title=title,
                url=url,
                media=media_items,
                outlet="The Guardian",
                section=section,
            )
            self._hydrate(article)
            articles.append(article)
        return articles

    def _hydrate(self, article: Article) -> None:
        """Fetch and parse the full article content."""
        if not article.url:
            return

        resp = self.session.get(
            article.url,
            headers=self.HEADERS,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        if resp.status_code >= 400:
            print(f"ERROR: Failed to fetch article {article.url}: {resp.status_code}")
            return

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract from JSON-LD
        try:
            json_ld_script = soup.find("script", {"type": "application/ld+json"})
            if json_ld_script:
                json_ld_data = json.loads(json_ld_script.string)
                if isinstance(json_ld_data, list):
                    json_ld = json_ld_data[0]
                else:
                    json_ld = json_ld_data

                article.title = json_ld.get("headline", article.title)
                article.published_at = json_ld.get("datePublished")
                article.author = ", ".join(
                    [author.get("name") for author in json_ld.get("author", [])]
                )
                article.summary = json_ld.get("description")

                keywords = json_ld.get("keywords")
                if isinstance(keywords, str):
                    article.tags = [tag.strip() for tag in keywords.split(",")]
                elif isinstance(keywords, list):
                    article.tags = keywords

                images = json_ld.get("image")
                if images and isinstance(images, list):
                    article.media = [
                        MediaItem(url=img_url, type="image") for img_url in images
                    ]

        except (json.JSONDecodeError, IndexError, KeyError):
            pass

        # Extract media caption from gu-island element
        lightbox_island = soup.find("gu-island", {"name": "LightboxLayout"})
        if lightbox_island and "props" in lightbox_island.attrs:
            try:
                props = json.loads(lightbox_island.attrs["props"])
                if "images" in props and isinstance(props["images"], list):
                    for img_data in props["images"]:
                        if "caption" in img_data and article.media:
                            # Assuming the first image in media corresponds to the first caption found
                            article.media[0].caption = img_data["caption"]
                            break
            except json.JSONDecodeError:
                pass

        # Extract tags from meta property as a fallback or supplement
        meta_tags = soup.find("meta", {"property": "article:tag"})
        if meta_tags and "content" in meta_tags.attrs:
            new_tags = [tag.strip() for tag in meta_tags["content"].split(",")]
            # Add new tags only if they are not already present
            for tag in new_tags:
                if tag not in article.tags:
                    article.tags.append(tag)

        # Extract content
        content_div = soup.find("div", {"id": "maincontent"})
        if content_div:
            paragraphs = content_div.find_all("p")
            article.content = "\n".join([p.get_text(strip=True) for p in paragraphs])


if __name__ == "__main__":
    scraper = TheGuardianScraper()
    articles = scraper.search("bangladesh", page=1, size=10)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.title}")
        print(f"  URL: {article.url}")
        if article.summary:
            print(f"  Summary: {article.summary[:100]}...")
        if article.content:
            print(f"  Content: {article.content[:200]}...")
        if article.author:
            print(f"  Author: {article.author}")
        if article.tags:
            print(f"  Tags: {', '.join(article.tags)}")
        if article.section:
            print(f"  Section: {article.section}")
        if article.media:
            print(f"  Media: {article.media[0].url}, {article.media[0].caption}")
    print(f"\n{len(articles)} articles found")
