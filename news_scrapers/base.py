# base.py – v2  (2025-07-09)
from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# ─────────────────────────── data models ────────────────────────────
@dataclass(slots=True)
class MediaItem:
    url: str
    caption: str | None = None
    type: str | None = None            # "image" / "video" / …

@dataclass(slots=True)
class Article:
    title: str | None = None
    published_at: str | None = None    # ISO-8601 string
    url: str | None = None
    content: str | None = None
    summary: str | None = None
    author: str | None = None
    media: list[MediaItem] = field(default_factory=list)
    outlet: str | None = None
    tags: list[str] = field(default_factory=list)
    section: str | None = None

# ───────────────────────────── helpers ──────────────────────────────
logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

def _build_session(max_retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
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

class ResponseKind(str, Enum):
    """What the remote endpoint returns *for the search call*."""
    JSON = "json"
    HTML = "html"
    AUTO = "auto"          # try JSON then fall back to text

# ──────────────────────────── base class ────────────────────────────
class BaseNewsScraper(ABC):
    """Common plumbing for every news-site scraper.

    Key new features
    ----------------
    *   **Class-level defaults** – `BASE_URL`, `HEADERS/COOKIES`,
        `PARAMS`, `PAYLOAD`.
        Sub-classes *may* simply override those constants
    *   **`RESPONSE_KIND` switch** – choose `"json"`, `"html"` or `"auto"`
        per scraper.
    *   **Browser hook** – set `USE_BROWSER = True` *or* override
        `_fetch_remote()` to integrate Selenium/Playwright without touching
        the rest of the pipeline.
    """

    # ---------- override these in subclasses ----------
    BASE_URL: str | None = None
    REQUEST_METHOD: str = "POST"               # "GET" or "POST"
    RESPONSE_KIND: ResponseKind = ResponseKind.JSON

    HEADERS: Dict[str, str] = {}
    COOKIES: Dict[str, str] = {}
    PARAMS: Dict[str, Any] = {}
    PAYLOAD: Dict[str, Any] = {}

    USE_BROWSER: bool = False                  # future Selenium/Playwright

    # ---------------------------------------------------
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int | tuple[int, int] = (5, 15),   # (connect, read)
        proxy: str | None = None,
    ) -> None:
        self.session = session or _build_session()
        self.timeout = timeout
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self._driver: Any = None # Initialize driver to None

    # ───────────────────── public entry-point ──────────────────────
    def search(self, keyword: str, page: int = 1, size: int = 30, **kwargs) -> List[Article]:
        """Return a list of `Article` objects for *keyword*."""

        data = self._fetch_remote(self.BASE_URL)
        articles = self._parse_response(data)

        # auto-summary shim
        for art in articles:
            if art.summary is None and art.content:
                art.summary = self._auto_summary(art.content)
        return articles

    # ─────────────────── overridable builders ──────────────────────

    @abstractmethod
    def _parse_response(self, data: Any) -> List[Article]:
        """Convert whatever `_fetch_remote` returned into `Article`s."""

    # ───────────────────── low-level I/O layer ─────────────────────
    def _fetch_remote(self, url: str, **kwargs) -> str | dict:
        """Fetch the search endpoint and return *json* or *html* accordingly."""

        # Browser automation shortcut
        if self.USE_BROWSER and self._driver is not None:
            return self._fetch_via_browser(url, self.PARAMS)

        method = self.REQUEST_METHOD.upper()
        start  = time.perf_counter()
        if method == "POST":
            resp = self.session.post(
                url, params=self.PARAMS, json=self.PAYLOAD or None,
                headers=self.HEADERS, cookies=self.COOKIES,
                timeout=self.timeout, proxies=self.proxies,
            )
        else:
            resp = self.session.get(
                url, params=self.PARAMS,
                headers=self.HEADERS, cookies=self.COOKIES,
                timeout=self.timeout, proxies=self.proxies,
            )
        latency = time.perf_counter() - start
        logger.info("%s %s [%s] %.2fs", method, url, resp.status_code, latency)
        if resp.status_code >= 400:
            logger.error("Bad response: %s", resp.text[:500])
            resp.raise_for_status()

        kind = self.RESPONSE_KIND
        if kind is ResponseKind.JSON:
            return resp.json()
        if kind is ResponseKind.HTML:
            return resp.text

        # AUTO – try JSON first, fall back to text
        try:
            return resp.json()
        except Exception:
            return resp.text

    # Browser helper – override/extend for Selenium/Playwright
    def _fetch_via_browser(self, url: str, params: Dict[str, Any]) -> str:  # noqa: D401
        if self.USE_BROWSER and not self._driver:
            self._init_browser()

        self._driver.get(url)
        return self._driver.page_source

    def _init_browser(self):
        """Initialize the browser driver."""
        if self._driver is None:
            import undetected_chromedriver as uc
            self._driver = uc.Chrome()

    def quit_browser(self):
        """Quit the browser driver if it's active."""
        if self._driver:
            try:
                self._driver.quit()
            except Exception as e:
                logger.debug(f"Exception during browser quit: {e}")
            finally:
                self._driver = None

    def __del__(self):
        self.quit_browser()

    # ------------------------------------------------------------------
    @staticmethod
    def _auto_summary(text: str, sentences: int = 2) -> str:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return " ".join(parts[: sentences]).strip()
