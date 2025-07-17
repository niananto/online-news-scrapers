from __future__ import annotations

"""FastAPI gateway for *single‑outlet* Shottify news scraping.

Run with::

    uvicorn server:app --reload --port 8000
    python server.py

Endpoint
~~~~~~~~
    POST /scrape

Request body::

    {
        "outlet": "hindustan_times" | "business_standard" | "news18" |
                  "firstpost" | "republic_world" | "india_dotcom",   // required
        "keyword": "<search term>",                           // default "bangladesh"
        "limit":   <int 1‒500>,                                // default 30
        "page_size": <int 1‒100>                              // default 50
    }

`/scrape` returns a **list[ArticleModel]**; each item:

    {
        "title": "…",
        "published_at": "2025‑07‑09T12:34:00+05:30",
        "url": "https://…",
        "content": "long body …",
        "summary": "first sentences …",
        "author": "Foo Bar" | ["Foo", "Bar"],   // ← str *or* list[str]
        "media": [ {"url": "…", "caption": "…", "type": "image"}, … ],
        "outlet": "Hindustan Times",
        "tags": ["politics", "asia"],
        "section": "world"
    }

The server now keeps paging *until either the requested **limit** is reached or
an **empty** batch is returned*, ensuring outlets like **India.com**—which cap
results to 24 per page—are fully traversed. This fixes the previous behaviour
where smaller‑than‑requested batches prematurely stopped pagination.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import List, Optional
import datetime

from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Scraper imports & registry
# ---------------------------------------------------------------------------
from news_scrapers import (
    HindustanTimesScraper,
    BusinessStandardScraper,
    News18Scraper,
    FirstpostScraper,
    RepublicWorldScraper,
    IndiaDotComScraper,
    StatesmanScraper,
    DailyPioneerScraper,
    SouthAsiaMonitorScraper,
    EconomicTimesScraper,
    IndiaTodayScraper,
    NdtvScraper,
    TheTribuneScraper,
    IndianExpressScraper,
    MillenniumPostScraper,
    TimesOfIndiaScraper,
    DeccanHeraldScraper,
    AbpLiveScraper,
)
from news_scrapers.base import Article  # for type hints only

SCRAPER_MAP = {
    "hindustan_times": HindustanTimesScraper,
    "business_standard": BusinessStandardScraper,
    "news18": News18Scraper,
    "firstpost": FirstpostScraper,
    "republic_world": RepublicWorldScraper,
    "india_dotcom": IndiaDotComScraper,
    "statesman": StatesmanScraper,
    "daily_pioneer": DailyPioneerScraper,
    "south_asia_monitor": SouthAsiaMonitorScraper,
    "economic_times": EconomicTimesScraper,
    "india_today": IndiaTodayScraper,
    "ndtv": NdtvScraper,
    "the_tribune": TheTribuneScraper,
    "indian_express": IndianExpressScraper,
    "millennium_post": MillenniumPostScraper,
    "times_of_india": TimesOfIndiaScraper,
    "deccan_herald": DeccanHeraldScraper,
    "abp_live": AbpLiveScraper,
}
OUTLET_CHOICES: set[str] = set(SCRAPER_MAP.keys())

# Thread‑pool for the blocking HTTP inside each scraper.
EXECUTOR = ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="Shottify Scraper API", version="0.1.1", docs_url="/")

# ---------------------------------------------------------------------------
# Pydantic models – request & response
# ---------------------------------------------------------------------------
class ScrapeRequest(BaseModel):
    outlet: str = Field(
        ..., description="Target news outlet; one of: " + ", ".join(sorted(OUTLET_CHOICES))
    )
    keyword: str = Field(
        "bangladesh", description="Search keyword (defaults to 'bangladesh')"
    )
    limit: int = Field(
        30,
        ge=1,
        le=500,
        description="Maximum number of articles to return (1–500)",
    )
    page_size: int = Field(
        50,
        ge=1,
        le=100,
        description="Maximum results we *ask* the outlet for per remote page (1–100)",
    )

    @field_validator("outlet")  # Pydantic v2 style
    def _check_outlet(cls, v: str) -> str:  # noqa: N805  (validator sig)
        if v.lower() not in OUTLET_CHOICES:
            raise ValueError(f"outlet must be one of {sorted(OUTLET_CHOICES)}")
        return v.lower()


class MediaItemModel(BaseModel):
    url: str
    caption: Optional[str] = None
    type: Optional[str] = None


class ArticleModel(BaseModel):
    title: Optional[str] = None
    published_at: str | int | float | datetime.datetime | None = None
    url: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    author: str | List[str] | None = None
    media: List[MediaItemModel] = []
    outlet: Optional[str] = None
    tags: List[str] = []
    section: str | List[str] | None = None

    @classmethod
    def from_article(cls, art: Article):  # type: ignore[override]
        data = asdict(art)
        ts = data.get("published_at")
        if isinstance(ts, (int, float)) and ts > 0:
            try:
                dt = datetime.datetime.fromtimestamp(ts)
                data["published_at"] = dt.isoformat()
            except Exception:
                data["published_at"] = str(ts)
        elif isinstance(ts, datetime.datetime):
            data["published_at"] = ts.isoformat()
        return cls(**data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _run_scraper(
    scraper_cls, keyword: str, limit: int, page_size: int
) -> List[Article]:
    """Collect articles, paging until *limit* or upstream exhaustion.

    Some outlets hard‑cap the number of results they return per page (e.g.
    **India.com**: 24).  We therefore continue fetching pages **until** we hit
    the requested *limit* **or** receive an **empty** list, instead of stopping
    the moment a batch is smaller than our requested *page_size*.
    """

    def _blocking_call() -> List[Article]:
        scraper = scraper_cls()
        collected: List[Article] = []
        page = 1
        while len(collected) < limit:
            requested = min(page_size, limit - len(collected))
            batch = scraper.search(keyword, page=page, size=requested)
            if not batch:
                break  # no more articles upstream
            collected.extend(batch)
            page += 1  # keep paging – scraper may have its own per‑page clamp
        return collected[:limit]

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(EXECUTOR, _blocking_call)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@app.post("/scrape", response_model=List[ArticleModel])
async def scrape(req: ScrapeRequest):
    scraper_cls = SCRAPER_MAP[req.outlet]
    articles = await _run_scraper(scraper_cls, req.keyword, req.limit, req.page_size)

    # Deduplicate by URL (thin safety‑net)
    seen: set[str] = set()
    unique: List[Article] = []
    for art in articles:
        if art.url and art.url not in seen:
            seen.add(art.url)
            unique.append(art)

    return [ArticleModel.from_article(a) for a in unique]


# ---------------------------------------------------------------------------
# Design Notes: scaling for large & long‑running jobs
# ---------------------------------------------------------------------------
"""
1. **Hard cap** – The route enforces *limit ≤ 500*. Empirically each outlet
   yields ~50‑100 articles in <10 s, so 500 is still feasible synchronously.

2. **Streaming** – For thousands of articles, switch to Server‑Sent Events
   (`EventSourceResponse`) or a chunked `StreamingResponse`, pushing articles
   as they arrive.

3. **Background queue** – Place heavy jobs onto a broker (Redis) with Celery or
   Dramatiq; return a `job_id` immediately, then poll `/result/{job_id}` or use
   a WebSocket for progress.

4. **Cache** – Store recent `(outlet, keyword)` queries in SQLite/Redis to
   avoid hammering third‑party APIs under load.
"""

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
