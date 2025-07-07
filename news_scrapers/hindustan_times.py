from __future__ import annotations

from typing import Any, Dict, List

from news_scrapers import BaseNewsScraper


class HindustanTimesScraper(BaseNewsScraper):
    """Scraper for Hindustan Times search API."""

    BASE_URL = "https://api.hindustantimes.com/api/articles/search"

    DEFAULT_HEADERS: Dict[str, str] = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/json",
        "origin": "https://www.hindustantimes.com",
        "referer": "https://www.hindustantimes.com/search",
    }

    # ------------- implementation details -------------
    def _build_payload(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:  # noqa: D401,E501
        """Render the JSON body expected by Hindustan Times."""
        return {
            "searchKeyword": keyword,
            "page": str(page),
            "size": str(size),
            "type": kwargs.get("type", "story"),
        }

    def _parse_response(self, response_json: Dict[str, Any]) -> List[Dict[str, Any]]:  # noqa: D401,E501
        """Return the flattened list of article dicts."""
        data = response_json.get("content")
        if isinstance(data, list):  # ← new shape (July 2025)
            return data
        # Fallback – return empty list rather than exploding up‑stack.
        return []


if __name__ == "__main__":
    scraper = HindustanTimesScraper()
    for art in scraper.search("bangladesh", page=1, size=5):
        print(f"{art.get('title') or art.get('headline')[:80]}\n→ {art.get('metadata', {}).get('canonicalUrl') or art.get('url')}\n")

