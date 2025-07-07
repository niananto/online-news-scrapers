from __future__ import annotations

import os
import json  # noqa: F401 (reserved for future log redaction)
import time
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def _build_session(max_retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:  # noqa: D401
    """Return a `requests.Session` pre‑wired with sane retry defaults."""
    session = requests.Session()
    retries = Retry(
        total=max_retries,
        connect=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session


class BaseNewsScraper(ABC):
    """Abstract base class for all news scrapers."""

    #: override these in subclasses
    BASE_URL: str | None = None
    DEFAULT_HEADERS: Dict[str, str] = {}

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int | tuple[int, int] = (5, 15),  # (connect, read)
        proxy: str | None = None,
    ) -> None:
        self.session = session or _build_session()
        self.timeout = timeout
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

    # ──────────────────────────────── public API ────────────────────────────────
    def search(self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any) -> List[Dict[str, Any]]:  # noqa: D401,E501
        """Return a list of article dictionaries for the given query."""
        payload = self._build_payload(keyword=keyword, page=page, size=size, **kwargs)
        logger.debug("Payload built: %s", payload)
        response_json = self._post_json(self.BASE_URL, payload)
        articles = self._parse_response(response_json)
        return articles

    # ───────────────────────────── hooks for subclasses ─────────────────────────
    @abstractmethod
    def _build_payload(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:  # noqa: D401,E501
        """Translate generic kwargs to portal‑specific JSON body."""

    @abstractmethod
    def _parse_response(self, response_json: Dict[str, Any]) -> List[Dict[str, Any]]:  # noqa: D401,E501
        """Extract a list of articles from the raw JSON payload."""

    # ─────────────────────────── helper methods (shared) ────────────────────────
    def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D401
        """Make a POST request with retries & error handling."""
        start = time.perf_counter()
        resp = self.session.post(
            url,
            json=payload,
            headers=self.DEFAULT_HEADERS,
            timeout=self.timeout,
            proxies=self.proxies,
        )
        latency = time.perf_counter() - start
        logger.info("POST %s [%s] %.2f s", url, resp.status_code, latency)
        if resp.status_code >= 400:
            logger.error("Error response: %s", resp.text[:500])
            resp.raise_for_status()
        return resp.json()
