import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from news_scrapers.base import Article, BaseNewsScraper, MediaItem, ResponseKind, logger

load_dotenv()


class AljazeeraScraper(BaseNewsScraper):
    """Scraper for **Aljazeera** using browser automation."""

    BASE_URL = "https://www.aljazeera.com/search/"
    REQUEST_METHOD = "GET"
    RESPONSE_KIND = ResponseKind.HTML
    USE_BROWSER = True

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    }

    def search(self, keyword: str, page: int = 1, size: int = 10, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""
        if size > 10:
            logger.warning("Aljazeera returns max 10 results per page. Setting size to 10.")
            size = 10

        data = self._fetch_remote(self.BASE_URL, keyword=keyword, page=page, size=size)
        articles = self._parse_response(data, page=page, size=size)

        return articles

    def _fetch_remote(self, url: str, **kwargs) -> str:
        """Fetch the search endpoint using the browser and handle pagination."""
        keyword = kwargs.get("keyword")
        page = kwargs.get("page", 1)
        size = kwargs.get("size", 10)

        if self._driver is None:
            self._init_browser()

        search_url = f"{url}{keyword}?sort=date"
        if self._driver.current_url != search_url:
            self._driver.get(search_url)

        # Wait for the page to load
        WebDriverWait(self._driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".search-result__list"))
        )

        # Handle cookie consent banner if present
        try:
            accept_cookies_button = WebDriverWait(self._driver, 5).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            accept_cookies_button.click()
            logger.info("Clicked cookie consent button.")
            time.sleep(1) # Give a moment for the banner to disappear
        except Exception:
            logger.info("No cookie consent banner found or clickable within 5 seconds.")

        # Calculate how many articles we need to load in total
        target_article_count = page * size
        current_article_count = 0
        max_articles_to_load = 100 # Limit to 100 articles as per requirement

        while current_article_count < target_article_count and current_article_count < max_articles_to_load:
            try:
                show_more_button = WebDriverWait(self._driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".show-more-button"))
                )
                show_more_button.click()
                time.sleep(2)  # Wait for content to load
                # Update current_article_count based on the number of articles currently displayed
                current_article_count = len(self._driver.find_elements(By.CSS_SELECTOR, ".search-result__list .gc__content"))
            except Exception as e:
                logger.info(f"No more 'Show more' button or error clicking: {e}")
                break

        return self._driver.page_source

    def _parse_response(self, html_data: str, page: int, size: int) -> List[Article]:
        """Convert the HTML response into a list of `Article` objects."""
        soup = BeautifulSoup(html_data, "lxml")
        all_articles: List[Article] = []

        # Find all article elements
        article_elements = soup.select(".search-result__list .gc__content")

        for element in article_elements:
            title_element = element.select_one(".gc__title a")
            url = title_element['href'] if title_element else None
            title = title_element.get_text(strip=True) if title_element else None

            summary_element = element.select_one(".gc__excerpt p")
            summary = summary_element.get_text(strip=True) if summary_element else None

            published_at_element = element.select_one(".gc__date span")
            published_at = published_at_element.get_text(strip=True) if published_at_element else None
            # TODO: Parse published_at into ISO format

            media_items = []
            image_element = element.select_one(".gc__image img")
            if image_element and image_element.get('src'):
                media_items.append(MediaItem(url=image_element['src'], type='image'))

            article = Article(
                title=title,
                url=url,
                summary=summary,
                published_at=published_at,
                media=media_items,
                outlet="Aljazeera",
            )
            all_articles.append(article)

        # Slice the articles to return only the ones for the requested page
        start_index = (page - 1) * size
        end_index = start_index + size
        return all_articles[start_index:end_index]


if __name__ == "__main__":
    scraper = AljazeeraScraper()
    try:
        print("\n--- Testing Search (Page 1) ---")
        articles_page1 = scraper.search(keyword="bangladesh", page=1, size=10)
        for article in articles_page1:
            print(f"Title: {article.title}")
            print(f"URL: {article.url}")
            print(f"Summary: {article.summary}")
            print(f"Published At: {article.published_at}")
            print(f"Media: {article.media}")
            print("---")
        print(f"Total articles on page 1: {len(articles_page1)}")

        print("\n--- Testing Search (Page 2) ---")
        articles_page2 = scraper.search(keyword="bangladesh", page=2, size=10)
        for article in articles_page2:
            print(f"Title: {article.title}")
            print(f"URL: {article.url}")
            print(f"Summary: {article.summary}")
            print(f"Published At: {article.published_at}")
            print(f"Media: {article.media}")
            print("---")
        print(f"Total articles on page 2: {len(articles_page2)}")

    finally:
        scraper.quit_browser()
