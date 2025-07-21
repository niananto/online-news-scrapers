import json
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class BBCScraper(BaseNewsScraper):
    """Scraper for **BBC**."""

    BASE_URL = "https://www.bbc.com/search"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML
    HEADERS = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'priority': 'u=0, i',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

    def search(self, keyword: str, page: int = 1, size: int = 9, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""
        if size > 9:
            logger.warning("BBC API allows a maximum of 9 items per page. Proceeding with size=9.")
            size = 9
        self.PARAMS = {"q": keyword, "page": page}
        # The 'size' parameter is not directly supported by the BBC search URL,
        # but we keep it in the signature for consistency.
        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, html: str) -> List[Article]:
        """Convert the HTML response into a list of `Article` objects."""
        soup = BeautifulSoup(html, "html.parser")
        articles: list[Article] = []

        next_data_script = soup.find("script", id="__NEXT_DATA__")
        if not next_data_script:
            return articles

        try:
            data = json.loads(next_data_script.string)
            results = list(data.get("props", {}).get("pageProps", {}).get("page", {}).values())[0].get("results", [])
        except (json.JSONDecodeError, AttributeError):
            return articles

        for item in results:
            title = item.get("title")
            relative_url = item.get("href")
            if not relative_url or "/audio/" in relative_url or "/videos/" in relative_url or "/live/" in relative_url:
                continue
            if relative_url.startswith("https://www.bbc.com"):
                url = relative_url
            else:
                url = f"https://www.bbc.com{relative_url}"
            summary = item.get("description")
            
            timestamp = item.get("metadata", {}).get("firstUpdated")
            if timestamp:
                # Convert timestamp from milliseconds to ISO 8601 format
                published_at = datetime.fromtimestamp(timestamp / 1000).isoformat()
            else:
                published_at = None

            media_items = []
            if image_data := item.get("image"):
                if image_model := image_data.get("model"):
                    if image_blocks := image_model.get("blocks"):
                        if image_src := image_blocks.get("src"):
                            media_items.append(MediaItem(url=image_src, type="image"))

            article = Article(
                title=title,
                url=url,
                summary=summary,
                published_at=published_at,
                outlet="BBC",
                media=media_items,
            )

            if article.url:
                try:
                    details = self._fetch_article_details(article.url)
                    article.content = details.get("content")
                    article.author = details.get("author")
                    if details.get("summary"):
                        article.summary = details.get("summary")
                except Exception as e:
                    logger.warning(f"Failed to hydrate article {article.url}: {e}")

            articles.append(article)
        return articles

    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """Fetch and parse the full article content based on URL type."""
        headers = self.HEADERS
        resp = self.session.get(url, headers=headers, timeout=self.timeout, proxies=self.proxies)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        details: Dict[str, Any] = {"content": None, "author": None}
        next_data_script = soup.find("script", id="__NEXT_DATA__")

        if "/news/articles/" in url:
            content_blocks = soup.find_all("div", attrs={"data-component": "text-block"})
            details["content"] = " ".join([p.get_text(strip=True) for p in content_blocks])
            if next_data_script:
                try:
                    data = json.loads(next_data_script.string)
                    contributors = data.get("props", {}).get("pageProps", {}).get("metadata", {}).get("contributors")
                    if contributors and isinstance(contributors, str):
                        details["author"] = contributors
                    if contributors and isinstance(contributors, list):
                        details["author"] = ", ".join([c.get("name") for c in contributors if c.get("name")])
                except (json.JSONDecodeError, AttributeError):
                    pass
        elif "/sport/" in url:
            article_body = soup.find("article")
            ld_json_script = soup.find("script", attrs={'type': 'application/ld+json', 'data-rh': 'true'})
            if ld_json_script:
                try:
                    ld_data = json.loads(ld_json_script.string)
                    details["summary"] = ld_data.get("description")
                    if ld_data.get("author") and isinstance(ld_data["author"], list):
                        for author_info in ld_data["author"]:
                            if author_info.get("name"):
                                details["author"] = author_info["name"]
                                break
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.warning(f"Error parsing JSON-LD for sport article {url}: {e}")
            article_body = soup.find("article")
            if article_body:
                text_blocks = article_body.find_all(['p', 'h2'])
                details["content"] = " ".join(block.get_text(strip=True) for block in text_blocks)
        
        return details


if __name__ == "__main__":
    scraper = BBCScraper()
    articles = scraper.search("bangladesh", page=1, size=50)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.author} - {article.title}\n"
              f"{article.url}\n"
              f"Summary: {article.summary}\n"
              f"Content: {article.content[:120] if article.content else ''} ...\n"
              f"{article.media}\n"
              f"{article.tags} - {article.section}\n")
    print(f"{len(articles)} articles found")