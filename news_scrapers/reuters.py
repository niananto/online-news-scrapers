import json
import re
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class ReutersScraper(BaseNewsScraper):
    """Scraper for **Reuters**."""

    BASE_URL = "https://www.reuters.com/pf/api/v3/content/fetch/articles-by-search-v2"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.JSON
    HEADERS = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

    def search(self, keyword: str, page: int = 1, size: int = 20, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""
        offset = (page - 1) * size
        self.PARAMS = {
            "query": json.dumps({
                "keyword": keyword,
                "offset": offset,
                "orderby": "display_date:desc",
                "size": size,
                "website": "reuters"
            }),
            "d": "300",
            "mxId": "00000000",
            "_website": "reuters",
        }
        # The 'referer' header needs to be dynamic based on the offset
        if page == 1:
            self.HEADERS['referer'] = 'https://www.reuters.com/site-search/?query=' + keyword
        else:
            self.HEADERS['referer'] = f'https://www.reuters.com/site-search/?query={keyword}&offset={offset}'

        return super().search(keyword, page, size, **kwargs)

    def _parse_response(self, json_response: Dict[str, Any]) -> List[Article]:
        """Convert the JSON response into a list of `Article` objects."""
        articles: List[Article] = []
        results = json_response.get("result", {}).get("articles", [])

        for item in results:
            title = item.get("title")
            url = item.get("canonical_url")
            if url and not url.startswith("http"):
                url = "https://www.reuters.com" + url
            summary = item.get("description")
            
            published_at = None
            if item.get("published_time"):
                try:
                    published_at = datetime.fromisoformat(item["published_time"].replace("Z", "+00:00")).isoformat()
                except ValueError:
                    pass

            media_items = []
            if item.get("thumbnail") and item["thumbnail"].get("url"):
                media_items.append(MediaItem(url=item["thumbnail"]["url"], type="image"))

            authors = []
            if item.get("authors"):
                for author_data in item["authors"]:
                    if author_name := author_data.get("name"):
                        authors.append(author_name)
            author = ", ".join(authors) if authors else None

            section = None
            if item.get("kicker") and item["kicker"].get("name"):
                section = item["kicker"]["name"]

            article = Article(
                title=title,
                url=url,
                summary=summary,
                published_at=published_at,
                outlet="Reuters",
                media=media_items,
                author=author,
                section=section,
            )

            if article.url:
                try:
                    details = self._fetch_article_details(article.url)
                    article.content = details.get("content")
                except Exception as e:
                    logger.warning(f"Failed to hydrate article {article.url}: {e}")

            articles.append(article)
        return articles

    def _fetch_article_details(self, url: str) -> Dict[str, Any]:
        """Fetch and parse the full article content based on URL."""
        headers = self.HEADERS
        resp = self.session.get(url, headers=headers, timeout=self.timeout, proxies=self.proxies)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        content = None
        fusion_metadata_script = soup.find("script", id="fusion-metadata")
        if fusion_metadata_script and fusion_metadata_script.string:
            try:
                # Use a more flexible regex to extract the JSON string assigned to window.Fusion.globalContent
                match = re.search(r"Fusion\.globalContent=(\{.*?\});", fusion_metadata_script.string, re.DOTALL)
                if match:
                    global_content_json = match.group(1)
                    global_content_data = json.loads(global_content_json)
                    if global_content_data.get("result") and global_content_data["result"].get("content_elements"):
                        content_elements = global_content_data["result"]["content_elements"]
                        content = " ".join([elem.get("content", "") for elem in content_elements if elem.get("type") == "paragraph"])
            except (json.JSONDecodeError, AttributeError, re.error) as e:
                logger.warning(f"Error parsing fusion-metadata script for {url}: {e}")

        if not content:
            article_body = soup.find("div", class_="article-body__content")
            if article_body:
                paragraphs = article_body.find_all("p")
                content = " ".join([p.get_text(strip=True) for p in paragraphs])

        return {"content": content}


if __name__ == "__main__":
    scraper = ReutersScraper()
    try:
        # Test search - Page 1
        print("\n--- Testing Search (Page 1) ---")
        articles_page1 = scraper.search(keyword="bangladesh", page=1, size=10)
        for article in articles_page1:
            print(f"Title: {article.title}")
            print(f"URL: {article.url}")
            print(f"Summary: {article.summary}")
            print(f"Published At: {article.published_at}")
            print(f"Outlet: {article.outlet}")
            print(f"Media: {article.media}")
            print(f"Author: {article.author}")
            print(f"Content: {article.content}")
            print("---")

        # Test search - Page 2
        print("\n--- Testing Search (Page 2) ---")
        articles_page2 = scraper.search(keyword="bangladesh", page=2, size=10)
        for article in articles_page2:
            print(f"Title: {article.title}")
            print(f"URL: {article.url}")
            print(f"Summary: {article.summary}")
            print(f"Published At: {article.published_at}")
            print(f"Outlet: {article.outlet}")
            print(f"Media: {article.media}")
            print(f"Author: {article.author}")
            print(f"Content: {article.content}")
            print("---")

    finally:
        scraper.quit_browser()