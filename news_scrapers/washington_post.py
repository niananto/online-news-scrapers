from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind


class WashingtonPostScraper(BaseNewsScraper):
    """Scraper for **The Washington Post** search API."""

    BASE_URL = "https://www.washingtonpost.com/search/api/search/"
    REQUEST_METHOD = "POST"
    RESPONSE_KIND = ResponseKind.JSON

    HEADERS: Dict[str, str] = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": "https://www.washingtonpost.com",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": "https://www.washingtonpost.com/search/?query=bangladesh",
        "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    }

    # Instance variable to store the next page token
    _next_page_token: Optional[str] = None

    def search(
        self, keyword: str, page: int = 1, size: int = 10, **kwargs: Any
    ) -> List[Article]:
        """Populate PAYLOAD, then delegate to the new base `search()`."""
        if size > 10:
            print("Washington Post returns max 10 results per page – truncating from %s", size)
            size = 10

        if page >= 2 and not self._next_page_token:
            print("you have to start searching from page 1, otherwise it won't work")
            return []
        
        self.PAYLOAD = {
            "searchTerm": keyword,
            "filters": {
                "sortBy": "relevancy",
                "dateRestrict": "",
                "start": 0,  # Always 0 as per sample, pagination is via nextPageToken
                "nextPageToken": self._next_page_token or "",
                "section": "",
                "author": "",
            },
        }
        # Clear PARAMS as it's a POST request with JSON payload
        self.PARAMS = {}

        # Call super().search to make the API request
        articles = super().search(keyword, page, size, **kwargs)
        return articles

    def _parse_response(self, json_data: Dict[str, Any]) -> List[Article]:
        """Convert the JSON response into a list of `Article` objects."""
        articles: list[Article] = []
        items = json_data.get("body", {}).get("items", [])

        for item in items:
            title = item.get("title")
            url = item.get("link")
            summary = self._clean_html(item.get("snippet"))

            published_at = None
            author = None
            section = None
            media_items = []
            tags = []

            # Extract data from pagemap metatags
            pagemap = item.get("pagemap", {})
            metatags = pagemap.get("metatags", [])
            if metatags:
                # Assuming the first metatag dictionary contains the relevant info
                meta = metatags[0]
                published_at = meta.get("article:published_time")
                # Author and section are not consistently available in search results, will handle in hydration
                section = meta.get("article:section")

                if og_image := meta.get("og:image"):
                    media_items.append(MediaItem(url=og_image, type="image"))

            article = Article(
                title=title,
                published_at=published_at,
                url=url,
                summary=summary,
                author=author,  # To be hydrated
                media=media_items,
                outlet="The Washington Post",
                tags=tags,  # To be hydrated
                section=section,
            )
            articles.append(article)
            self._fetch_article_details(article) # Hydrate the article

        # Update next page token for subsequent calls
        search_info = json_data.get("body", {}).get("searchInformation", {})
        self._next_page_token = search_info.get("nextPageToken")

        return articles

    def _fetch_article_details(self, article: Article) -> None:
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

        # Extract data from __NEXT_DATA__ script
        next_data_script = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data_script and next_data_script.string:
            try:
                next_data = json.loads(next_data_script.string)
                global_content = next_data.get("props", {}).get("pageProps", {}).get("globalContent", {})

                # Author
                if authors_str := global_content.get("additional_properties", {}).get("authors"):
                    article.author = ", ".join([author.strip() for author in authors_str.split(',')])

                # Published Date
                if published_date := global_content.get("additional_properties", {}).get("published_date"):
                    # Convert Unix timestamp (milliseconds) to ISO-8601 string
                    try:
                        article.published_at = datetime.fromtimestamp(published_date / 1000).isoformat()
                    except (TypeError, ValueError):
                        pass

                # Content and Media
                content_parts = []
                if content_elements := global_content.get("content_elements"):
                    for element in content_elements:
                        if element.get("type") == "text" and element.get("content"):
                            content_parts.append(self._clean_html(element["content"]))
                        elif element.get("type") == "image" and element.get("url"):
                            caption = element.get("caption")
                            article.media.append(MediaItem(url=element["url"], caption=caption, type="image"))
                if content_parts:
                    article.content = "\n".join(content_parts)

                # Tags
                if taxonomies := global_content.get("additional_properties", {}).get("taxonomies"):
                    if wapo_topics := taxonomies.get("WaPo", {}).get("topics"):
                        article.tags = [topic.get("topic_name") for topic in wapo_topics if topic.get("topic_name")]

            except json.JSONDecodeError as e:
                print(f"Error parsing __NEXT_DATA__ for {article.url}: {e}")

        # Extract author from wpMetaData script
        wp_meta_data_script = soup.find("script", {"id": "wpMetaData"})
        if wp_meta_data_script and wp_meta_data_script.string:
            try:
                # Extract the JSON string from the JavaScript variable assignment
                match = re.search(r"var wpMetaData = ({.*?});", wp_meta_data_script.string, re.DOTALL)
                if match:
                    wp_meta_data = json.loads(match.group(1))
                    if authors_str := wp_meta_data.get("authors"):
                        # Replace thin space with regular space before splitting
                        authors_str = authors_str.replace('\u2009', ' ')
                        article.author = ", ".join([author.strip() for author in authors_str.split(',')])
            except json.JSONDecodeError as e:
                print(f"Error parsing wpMetaData for {article.url}: {e}")

        # Fallback to meta tags and DOM parsing if data not found in __NEXT_DATA__
        if not article.author:
            if author_meta := soup.find("meta", {"name": "author"}):
                article.author = author_meta.get("content")

        if not article.published_at:
            if published_meta := soup.find("meta", {"property": "article:published_time"}):
                article.published_at = published_meta.get("content")

        if not article.content:
            # Look for common article body containers
            article_body_div = soup.find("div", class_="article-body") or soup.find("div", class_="wp-story-body")
            if article_body_div:
                paragraphs = article_body_div.find_all("p")
                article.content = "\n".join([p.get_text(strip=True) for p in paragraphs])

        if not article.tags:
            if keywords_meta := soup.find("meta", {"name": "keywords"}):
                article.tags = [tag.strip() for tag in keywords_meta.get("content", "").split(",") if tag.strip()]

        if not article.media:
            if og_image_meta := soup.find("meta", {"property": "og:image"}):
                if og_image_url := og_image_meta.get("content"):
                    article.media.append(MediaItem(url=og_image_url, type="image"))

    @staticmethod
    def _clean_html(raw: str | None) -> str | None:
        """Strip *raw* HTML → plain text; collapse whitespace; decode entities."""
        if not raw:
            return None
        text = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = WashingtonPostScraper()
    all_articles = []
    page_num = 1
    while True:
        print(f"--- Page {page_num} ---")
        articles_on_page = scraper.search("bangladesh", page=page_num, size=10)
        
        # Hydrate each article
        for article in articles_on_page:
            scraper._fetch_article_details(article)
            all_articles.append(article)

        for article in articles_on_page:
            print(f"{article.published_at} – {article.outlet} - {article.title}")
            print(f"  URL: {article.url}")
            if article.summary:
                print(f"  Summary: {article.summary[:100]}...")
            if article.content:
                print(f"  Content: {article.content[:200].encode('utf-8', 'ignore').decode('utf-8')}...")
            if article.author:
                print(f"  Author: {article.author.encode('utf-8', 'ignore').decode('utf-8')}")
            if article.tags:
                print(f"  Tags: {', '.join(article.tags).encode('utf-8', 'ignore').decode('utf-8')}")
            if article.section:
                print(f"  Section: {article.section.encode('utf-8', 'ignore').decode('utf-8')}")
            if article.media:
                print(f"  Media: {article.media[0].url}")
                if article.media[0].caption:
                    print(f"  Caption: {article.media[0].caption.encode('utf-8', 'ignore').decode('utf-8')}")

        if not scraper._next_page_token or not articles_on_page: # Stop if no more pages or no articles on current page
            break
        
        page_num += 1
        if page_num >= 3: break # Limit to 2 pages for demo purposes

    print(f"\nTotal {len(all_articles)} articles found.")
