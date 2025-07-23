from __future__ import annotations

import json
import re
import base64
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from news_scrapers.base import Article, BaseNewsScraper, ResponseKind, logger, MediaItem


class NewYorkTimesScraper(BaseNewsScraper):
    """Scraper for **The New York Times** search."""

    BASE_URL = "https://www.nytimes.com/search"
    GRAPHQL_URL = "https://samizdat-graphql.nytimes.com/graphql/v2"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML
    USE_BROWSER = True

    # This is the hardcoded SHA256 hash for the persisted query
    PERSISTED_QUERY_HASH = "2f5041641b9de748b42e5732e25b735d26f0ae188c900e15029287f391427ddf"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._nyt_token: Optional[str] = None
        self._cursor: Optional[str] = None
        self._fetched_until = 0

    @staticmethod
    def _find_first_non_null_in_obj(obj: Any, key: str) -> Optional[str]:
        """Recursively search for the first non-null value of a key in a nested object."""
        if isinstance(obj, dict):
            if key in obj and obj[key] is not None:
                return obj[key]
            for value in obj.values():
                found = NewYorkTimesScraper._find_first_non_null_in_obj(value, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = NewYorkTimesScraper._find_first_non_null_in_obj(item, key)
                if found is not None:
                    return found
        return None

    def _extract_tokens_from_html(self, html_data: str):
        """Extracts the nyt-token and initial cursor from the HTML content."""
        # Extract nyt-token
        token_match = re.search(r'"nyt-token":"([^"]+)"', html_data)
        if token_match:
            self._nyt_token = token_match.group(1)
            logger.info("Found nyt-token.")
        else:
            logger.warning("Could not find nyt-token in HTML.")

        # Find the script tag containing the preloaded data
        soup = BeautifulSoup(html_data, "lxml")
        script_tag = soup.find("script", string=re.compile(r"window\.__preloadedData"))

        if not script_tag or not script_tag.string:
            logger.warning("Could not find script tag with window.__preloadedData.")
            return

        # Extract the JSON-like string from the script tag
        match = re.search(r"\"endCursor\"\s*:\s*\"(.*?)\"", script_tag.string, re.DOTALL)
        if match:
            self._cursor = match.group(1)
            logger.info("Found endCursor.")
        else:
            logger.warning("Could not extract JSON object from preloaded data script.")
            return

    def search(self, keyword: str, page: int = 1, size: int = 10, **kwargs: Any) -> List[Article]:
        """
        Search for articles on The New York Times.
        The first page request hits the standard search URL to get the initial HTML
        and extract the necessary tokens. Subsequent pages use the GraphQL API.
        """
        if size > 10:
            logger.warning("New York Times search is limited to 10 articles per page.")
            size = 10

        if not self._fetched_until == page-1:
            logger.error("You must fetch all previous pages first")
            return []

        if page == 1:
            # First call for this scraper instance. Fetch HTML and tokens.
            self.REQUEST_METHOD = "GET"
            self.RESPONSE_KIND = ResponseKind.HTML
            self.BASE_URL = "https://www.nytimes.com/search"
            self.PARAMS = {"lang": "en", "query": keyword, "sort": "newest", "types": "article"}
            logger.info("Performing initial fetch to get tokens.")
            html_data = self._fetch_remote(self.BASE_URL)
            if isinstance(html_data, str):
                self._extract_tokens_from_html(html_data)
            else:
                logger.error("Failed to fetch initial HTML page.")
                return []

            logger.info("Page 1 data available from initial HTML. Parsing now.")
            self._fetched_until = page
            return self._parse_response(html_data)

        # This is for page > 1
        if not self._nyt_token or self._cursor is None:
            logger.error("Token or cursor not available for paginated search. Please ensure search starts from page 1.")
            return []

        logger.info(f"Fetching page {page} with cursor {self._cursor}")
        self.REQUEST_METHOD = "GET"
        self.RESPONSE_KIND = ResponseKind.JSON
        self.BASE_URL = self.GRAPHQL_URL
        self.HEADERS.update({
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/json",
            "nyt-app-type": "project-vi",
            "nyt-app-version": "0.0.5",
            "nyt-token": self._nyt_token,
            "origin": "https://www.nytimes.com",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": "https://www.nytimes.com/",
            "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "x-nyt-internal-meter-override": "undefined",
        })
        self.COOKIES.update({
            "nyt-a": "3id1b3_zVd4CE7GSgaUHgv",
            "nyt-gdpr": "0",
            "nyt-purr": "cfhhcfhhhukfhufshgas2fdnd",
            "_gcl_au": "1.1.1500081809.1753278451",
        })

        variables = {
            "first": size,
            "sort": "newest",
            "lang": "EN",
            "text": keyword,
            "filterQuery": '((type: \"article\"))',
            "sectionFacetFilterQuery": '((type: \"article\"))',
            "typeFacetFilterQuery": "",
            "sectionFacetActive": True,
            "typeFacetActive": True,
            "cursor": self._cursor,
        }
        extensions = {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": self.PERSISTED_QUERY_HASH,
            }
        }
        self.PARAMS = {
            "operationName": "SearchRootQuery",
            "variables": json.dumps(variables),
            "extensions": json.dumps(extensions),
        }

        self.quit_browser()
        response_data = self._fetch_remote(self.GRAPHQL_URL)

        if response_data and isinstance(response_data, dict):
            logger.info(f"Successfully fetched page {page} for keyword '{keyword}'.")
            self._fetched_until = page

            next_cursor = self._find_first_non_null_in_obj(response_data, "endCursor")
            if next_cursor:
                self._cursor = next_cursor
                logger.info(f"Updated cursor for next page: {self._cursor}")
            else:
                logger.info("No more pages. End of results.")
                self._cursor = None
            return self._parse_response(response_data)
        else:
            logger.error(f"Failed to fetch page {page} for keyword '{keyword}'.")
            return []

    def _parse_response(self, response: Any) -> List[Article]:
        if isinstance(response, str):  # HTML response for page 1
            articles = self._parse_html_response(response)
        elif isinstance(response, dict):  # JSON response for page > 1
            articles = self._parse_json_response(response)
        else:
            return []

        for article in articles:
            details = self._fetch_article_details(article.url)
            if details:
                logger.info(f"Successfully fetched article {article.url}.")
                article.content = details["content"]
                article.media.extend(details["media"])
                article.author = details["author"] or article.author
        return articles

    @staticmethod
    def _parse_html_response(html_data: str) -> List[Article]:
        articles: List[Article] = []
        soup = BeautifulSoup(html_data, "lxml")

        script_tag = soup.find("script", string=re.compile(r"window\.__preloadedData"))
        json_start_match = re.search(r"window\.__preloadedData\s*=\s*(\{.*\});", script_tag.string, re.DOTALL)
        json_string = json_start_match.group(1)

        # Replace JavaScript-specific values with valid JSON equivalents
        json_string = json_string.replace("undefined", "null")
        json_string = re.sub(r'function\(.*?\)\{.*?\},', '"",', json_string)
        try:
            preloaded_data = json.loads(json_string + '}')
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return []

        initial_state = preloaded_data.get("initialState", {})

        for key, value in initial_state.items():
            if key.startswith("Article:"):
                title = value.get("promotionalHeadline")
                published_at = value.get("firstPublished")
                summary = value.get("summary")

                # Attempt to extract URL from the ID if available
                article_id = value.get("id")
                url = value.get("url")

                # Extract author (if available in this structure)
                author = None
                if "bylines" in value and isinstance(value["bylines"], list) and len(value["bylines"]) > 0:
                    author = value["bylines"][0].get("renderedRepresentation")

                # Extract media (if available in this structure)
                media_items = []
                promotional_media = value.get("promotionalMedia")
                if promotional_media and promotional_media.get("crops"):
                    first_crop = promotional_media["crops"][0]
                    if first_crop.get("renditions"):
                        first_rendition = first_crop["renditions"][0]
                        if first_rendition.get("url"):
                            media_items.append(MediaItem(url=first_rendition["url"], type="image",
                                                         caption=promotional_media.get("caption").get("text"),))

                articles.append(
                    Article(
                        title=title,
                        url=url,
                        published_at=published_at,
                        summary=summary,
                        author=author,
                        media=media_items,
                        outlet="The New York Times",
                    )
                )
        return articles

    @staticmethod
    def _parse_json_response(json_data: Dict) -> List[Article]:
        articles: List[Article] = []
        hits = json_data.get("data", {}).get("search", {}).get("hits", {}).get("edges", [])

        for hit in hits:
            node = hit.get("node", {})
            if not node:
                continue

            title = node.get("creativeWorkHeadline", {}).get("default")
            published_at = node.get("firstPublished")
            url = node.get("url")
            summary = node.get("creativeWorkSummary")
            author = None
            bylines = node.get("bylines")
            if bylines and isinstance(bylines, list) and len(bylines) > 0:
                author = bylines[0].get("renderedRepresentation")

            media_items = []
            promotional_media = node.get("promotionalMedia")
            if promotional_media and promotional_media.get("crops"):
                # Take the first rendition of the first crop as the main image
                first_crop = promotional_media["crops"][0]
                if first_crop.get("renditions"):
                    first_rendition = first_crop["renditions"][0]
                    if first_rendition.get("url"):
                        media_items.append(MediaItem(url=first_rendition["url"], type="image",
                                                     caption=promotional_media.get("caption").get("text")))

            section = node.get("section").get("displayName")
            tags = [] # Tags are not directly available in this JSON structure

            articles.append(
                Article(
                    title=title,
                    url=url,
                    published_at=published_at,
                    summary=summary,
                    author=author,
                    media=media_items,
                    outlet="The New York Times",
                    section=section,
                    tags=tags,
                )
            )
        return articles


    def _fetch_article_details(self, url: str) -> dict:
        html_content = self._fetch_via_browser(url, {})
        soup = BeautifulSoup(html_content, "lxml")

        out = {
            "title": None,
            "author": None,
            "content": None,
            "published_at": None,
            "media": [],
        }

        # # Extract Title (from meta tag or title tag)
        # title_meta = soup.find("meta", attrs={"property": "og:title"})
        # if title_meta:
        #     out["title"] = title_meta.get("content")
        # else:
        #     title_tag = soup.find("title")
        #     if title_tag:
        #         out["title"] = title_tag.get_text(strip=True).replace(" - The New York Times", "")

        # Extract Author
        author_meta = soup.find("meta", attrs={"name": "byl"})
        if author_meta:
            out["author"] = author_meta.get("content", "").replace("By ", "")

        # Extract Published Date
        published_meta = soup.find("meta", attrs={"property": "article:published_time"})
        if published_meta:
            out["published_at"] = published_meta.get("content")

        # Extract Content
        article_body = soup.find("section", attrs={"name": "articleBody"})
        if article_body:
            paragraphs = article_body.find_all("p")
            out["content"] = "\n".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])

        # Extract Media (main image)
        main_image_meta = soup.find("meta", attrs={"property": "og:image"})
        if main_image_meta:
            img_url = main_image_meta.get("content")
            img_alt = soup.find("meta", attrs={"property": "og:image:alt"})
            caption = img_alt.get("content") if img_alt else None
            if img_url:
                out["media"].append(MediaItem(url=img_url, caption=caption, type="image"))
        return out


if __name__ == "__main__":
    scraper = NewYorkTimesScraper()
    for page_no in range(1, 4):
        print(f"-----Fetching page {page_no}------------------")
        arts = scraper.search("bangladesh", page=page_no, size=50)
        for art in arts:
            print(f"Title: {art.title}")
            print(f"URL: {art.url}")
            print(f"Summary: {art.summary}")
            print(f"Author: {art.author}")
            print(f"Published at: {art.published_at}")
            print(f"Section: {art.section}")
            print(f"Tags: {art.tags}")
            print(f"Content: {art.content}")
            print(f"Media: {art.media}")
            print("----------------------------------------------------------")
