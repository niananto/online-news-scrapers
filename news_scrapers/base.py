from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


@dataclass(slots=True)
class MediaItem:
    url: str
    caption: str | None = None
    type: str | None = None  # "image" / "video" / etc.


@dataclass(slots=True)
class Article:
    title: str | None = None
    published_at: str | None = None  # ISO 8601 string
    url: str | None = None
    content: str | None = None
    summary: str | None = None
    author: str | None = None
    media: list[MediaItem] = field(default_factory=list)
    outlet: str | None = None
    tags: list[str] = field(default_factory=list)
    section: str | None = None


logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def _build_session(max_retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:  # noqa: D401
    """Return a `requests.Session` wired with sane retry defaults."""

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

    # ─────────────── public API ───────────────

    def search(
        self, keyword: str, page: int = 1, size: int = 30, **kwargs: Any
    ) -> List[Article]:
        """Return a list of `Article` objects for the given query."""

        payload = self._build_payload(keyword=keyword, page=page, size=size, **kwargs)
        logger.debug("Payload built: %s", payload)
        data = self._post_json(self.BASE_URL, payload)
        raw_items = self._parse_response(data)

        # Ensure every article has a summary – subclasses may leave it blank.
        for art in raw_items:
            if art.summary is None and art.content:
                art.summary = self._auto_summary(art.content)
        return raw_items

    # ─────────────── subclass hooks ───────────────

    @abstractmethod
    def _build_payload(self, *, keyword: str, page: int, size: int, **kwargs: Any) -> Dict[str, Any]:
        """Return the POST body expected by the remote service."""

    @abstractmethod
    def _parse_response(self, response_json: Dict[str, Any]) -> List[Article]:
        """Convert API JSON → list[Article]."""

    # ─────────────── helpers ───────────────

    @staticmethod
    def _auto_summary(text: str, sentences: int = 2) -> str:
        """Naïve summariser – first *n* sentences (period‑based split)."""

        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return " ".join(parts[: sentences]).strip()

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
            logger.error("Bad response: %s", resp.text[:500])
            resp.raise_for_status()
        return resp.json()
