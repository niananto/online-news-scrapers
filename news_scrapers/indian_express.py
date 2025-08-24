from __future__ import annotations

"""The Indian Express keyword-search scraper."""

import html
import json
import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore

from news_scrapers import BaseNewsScraper
from news_scrapers.base import Article, MediaItem, ResponseKind


class IndianExpressScraper(BaseNewsScraper):
    """Scraper for **The Indian Express** public search API."""

    BASE_URL = "https://indianexpress.com/wp-admin/admin-ajax.php"
    REQUEST_METHOD = "POST"
    RESPONSE_KIND = ResponseKind.HTML

    tag_id = None
    tag_security = None
    
    HEADERS: Dict[str, str] = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://indianexpress.com",
        "referer": "https://indianexpress.com/about/bangladesh/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
    }
    COOKIES: Dict[str, str] = {
        "ssostate": "PMYjbh",
        "_fbp": "fb.1.1752770453003.111824628482986679",
        "fpid": "719da45a6d77c3f5ca193896891c7068",
        "upssid": "719da45a6d77c3f5ca193896891c7068",
        "current_city_newname": "other city",
        "fpuuid": "45779822818954",
        "uplad": "2025-07-17",
        "ev_sid": "687927960d763703f724b328",
        "ev_did": "687927960d763703f724b327",
        "ie_userdata": '{"subscription_plan":[],"requireEntitlement":true}',
        "ev_user_state": "guest",
        "_parsely_session": '{"sid":1,"surl":"https://indianexpress.com/about/bangladesh/","sref":"","sts":1752770457158,"slts":0}',
        "_parsely_visitor": '{"id":"pid=89f9000cb38752620649f481ff7771e9","session_count":1,"last_session_ts":1752770457158}',
        "mo_guest_attr_sent": "1",
        "userLoyaltyBand": '{"plb":"Repeat","slb":"Casual"}',
        "peUserInActive": "3",
    }

    def _fetch_tag_details(self, keyword: str) -> None:
        resp = self.session.get("https://indianexpress.com/about/" + keyword, headers=self.HEADERS, cookies=self.COOKIES)
        soup = BeautifulSoup(resp.content, "lxml")

        self.tag_id = soup.find('input', attrs={'name': 'tag_id'})['value']
        self.tag_security = soup.find('input', attrs={'name': 'load-tag-data-ajax-nonce'})['value']

    def search(
        self, keyword: str, page: int = 1, size: int = 10, **kwargs: Any
    ) -> List[Article]:
        """Populate PARAMS, then delegate to the new base `search()`."""

        if size > 10:
            print("Indian Express returns max 10 results per page – truncating from %s",size)
            size = 10

        if not self.tag_id or not self.tag_security:
            self._fetch_tag_details(keyword)

        self.PAYLOAD = {
            "action": "load_tag_data",
            "tag_security": self.tag_security,
            "tag_page": page,
            "tag_id": self.tag_id,
            "post_type": "article",
            "utm_source": "",
            "profile_temp": "",
        }
        return super().search(keyword, page, size, **kwargs)

    def _fetch_remote(self, url: str, **kwargs) -> str | dict:
        """Fetch the search endpoint and return *html*."""
        resp = self.session.post(
            url,
            params=self.PARAMS,
            data=self.PAYLOAD or None,
            headers=self.HEADERS,
            cookies=self.COOKIES,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        if resp.status_code >= 400:
            raise Exception(f"HTTP error {resp.status_code}: {resp.text}")
        return resp.text

    # def _get_tag_id_from_keyword(self, keyword: str) -> str | None:
    #     """Fetches the tag ID for a given keyword from the Indian Express website."""
    #     tag_url = f"https://indianexpress.com/about/{keyword}/"
    #     try:
    #         resp = self.session.get(
    #             tag_url,
    #             headers=self.HEADERS,
    #             cookies=self.COOKIES,
    #             timeout=self.timeout,
    #             proxies=self.proxies,
    #         )
    #         resp.raise_for_status() # Raise HTTPError for bad responses
    #
    #         link_header = resp.headers.get('Link')
    #         if link_header:
    #             # Regex to find the tag ID in the Link header
    #             match = re.search(r'wp/v2/tags/(\d+)', link_header)
    #             if match:
    #                 return match.group(1)
    #     except Exception as e:
    #         print(f"ERROR: Error fetching tag ID for '{keyword}': {e}")
    #     return None

    def _fetch_article_details(self, article: Article) -> None:
        """Fetch and parse the full article content."""
        if not article.url:
            return

        resp = self.session.get(
            article.url,
            headers=self.HEADERS,
            cookies=self.COOKIES,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        if resp.status_code >= 400:
            # Log the error, but don't raise an exception to allow other articles to be processed
            print(f"ERROR: Failed to fetch article {article.url}: {resp.status_code}")
            return

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract content
        content_div = soup.find("div", id="pcl-full-content")
        if content_div:
            article.content = self._clean_html(str(content_div))

        # Extract author
        author_element = soup.find("div", class_="editor-date-logo")
        if author_element:
            author_link = author_element.find("a")
            if author_link:
                article.author = author_link.get_text(strip=True)

        # Extract tags
        tags_div = soup.find("div", class_="storytags")
        if tags_div:
            tags = [a.get_text(strip=True) for a in tags_div.find_all("a")]
            article.tags = tags

        # Extract section (from breadcrumb)
        breadcrumb = soup.find("ol", class_="m-breadcrumb")
        if breadcrumb:
            # Get the last but one list item, which is usually the section
            section_element = breadcrumb.find_all("li")
            if len(section_element) >= 2:
                article.section = section_element[-2].get_text(strip=True)

    @staticmethod
    def _clean_html(raw: str | None) -> str | None:
        if not raw:
            return None
        raw_unescaped: str = html.unescape(raw)
        text: str = BeautifulSoup(raw_unescaped, "lxml").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None

    def _parse_response(self, html_data: str) -> List[Article]:
        """Convert the HTML response into a list of `Article` objects."""
        # The response is a JSON-encoded string containing HTML, so unescape it first
        unescaped_html = json.loads(html_data)
        soup = BeautifulSoup(unescaped_html, "lxml")
        articles: list[Article] = []
        for item in soup.find_all("div", class_="details"):
            title_element = item.find("h3").find("a")
            title = title_element.get("title")
            url = title_element.get("href")
            
            image_element = item.find("img")
            image_url = image_element.get("src") if image_element else None
            
            summary_element = item.find_all("p")
            published_at = summary_element[0].text.strip() if summary_element else None
            summary = summary_element[1].text.strip() if len(summary_element) > 1 else None

            media_items = []
            if image_url:
                media_items.append(MediaItem(url=image_url, type="image"))

            article = Article(
                title=title,
                published_at=published_at,
                url=url,
                summary=summary,
                media=media_items,
                outlet="The Indian Express",
            )
            self._fetch_article_details(article) # Hydrate the article
            articles.append(article)
        return articles


# ───────────────────────────── tiny demo ──────────────────────────────
if __name__ == "__main__":  # pragma: no cover – manual smoke‑test
    scraper = IndianExpressScraper()
    articles = scraper.search("bangladesh", page=1, size=10)
    for article in articles:
        print(f"{article.published_at} – {article.outlet} - {article.title}")
        print(f"  URL: {article.url}")
        if article.summary:
            print(f"  Summary: {article.summary[:100]}...")
        if article.content:
            print(f"  Content: {article.content[:500]}...")
        if article.author:
            print(f"  Author: {article.author}")
        if article.tags:
            print(f"  Tags: {', '.join(article.tags)}")
        if article.section:
            print(f"  Section: {article.section}")
        if article.media:
            print(f"  Media: {article.media[0].url}")
    print(f"\n{len(articles)} articles found")
