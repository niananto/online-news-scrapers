from __future__ import annotations

"""Unified FastAPI server with scraping, database population, and scheduling.

Run with::
    python unified_server.py
    uvicorn unified_server:app --reload --port 8000

New Features:
- Scrape and populate database in single call
- Automated scheduling with configurable intervals
- Database statistics and monitoring
- Manual trigger endpoints
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import List, Optional, Dict, Any
import datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# Import existing server components
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
    TheQuintScraper,
    TheGuardianScraper,
    WashingtonPostScraper,
    WionScraper,
    TelegraphIndiaScraper,
    TheHinduScraper,
    BBCScraper,
    CNNScraper,
)
from news_scrapers.base import Article
from database_service import DatabaseService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Scraper registry
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
    "the_quint": TheQuintScraper,
    "the_guardian": TheGuardianScraper,
    "washington_post": WashingtonPostScraper,
    "wion": WionScraper,
    "telegraph_india": TelegraphIndiaScraper,
    "the_hindu": TheHinduScraper,
    "bbc": BBCScraper,
    "cnn": CNNScraper,
}
OUTLET_CHOICES: set[str] = set(SCRAPER_MAP.keys())

# Thread pool and services
EXECUTOR = ThreadPoolExecutor(max_workers=4)
db_service = DatabaseService()
scheduler = AsyncIOScheduler()

# FastAPI app
app = FastAPI(
    title="Unified News Scraper API", 
    version="1.0.0", 
    description="Scrape news and populate database with scheduling",
    docs_url="/"
)

# Scheduler configuration
SCHEDULER_CONFIG = {
    'outlets': [
        'hindustan_times',
        'business_standard',
        'news18',
        'firstpost',
        'republic_world',
        'india_dotcom',
        'statesman',
        'daily_pioneer',
        'south_asia_monitor',
        'economic_times',
        'india_today',
        'ndtv',
        'the_tribune',
        'indian_express',
        'millennium_post',
        'times_of_india',
        'deccan_herald',
        'abp_live',
        'the_quint',
        'the_guardian',
        'washington_post',
        'wion',
        'telegraph_india',
        'the_hindu',
        'bbc',
        'cnn'
    ],
    'keyword': 'bangladesh',
    'limit': 5,
    'page_size': 25,
    'interval_minutes': 5,  # Run every 30 minutes
    # Enhanced scheduler options for graceful handling
    'max_instances': 1,           # Prevent overlapping jobs
    'coalesce': True,             # Combine missed runs
    'misfire_grace_time': 60,    # 5 minutes grace for delayed starts
    'jitter': 10,                 # Add randomness to prevent thundering herd
    'max_retries_per_outlet': 2,  # Retry failed outlets
    'timeout_per_outlet': 180,    # 3 minutes timeout per outlet
    'circuit_breaker_threshold': 5, # Skip outlet after 5 consecutive failures
}

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class ScrapeRequest(BaseModel):
    outlet: str = Field(..., description="Target news outlet")
    keyword: str = Field("bangladesh", description="Search keyword")
    limit: int = Field(30, ge=1, le=500, description="Maximum articles (1-500)")
    page_size: int = Field(50, ge=1, le=100, description="Page size (1-100)")

    @field_validator("outlet")
    def _check_outlet(cls, v: str) -> str:
        if v.lower() not in OUTLET_CHOICES:
            raise ValueError(f"outlet must be one of {sorted(OUTLET_CHOICES)}")
        return v.lower()

class ScrapeAndPopulateRequest(BaseModel):
    outlets: List[str] = Field(..., description="List of outlets to scrape")
    keyword: str = Field("bangladesh", description="Search keyword")
    limit: int = Field(30, ge=1, le=500, description="Maximum articles per outlet")
    page_size: int = Field(50, ge=1, le=100, description="Page size")
    
    @field_validator("outlets")
    def _check_outlets(cls, v: List[str]) -> List[str]:
        invalid = [outlet for outlet in v if outlet.lower() not in OUTLET_CHOICES]
        if invalid:
            raise ValueError(f"Invalid outlets: {invalid}. Must be from {sorted(OUTLET_CHOICES)}")
        return [outlet.lower() for outlet in v]

class SchedulerConfigRequest(BaseModel):
    outlets: List[str] = Field(..., description="Outlets to scrape automatically")
    keyword: str = Field("bangladesh", description="Search keyword")
    limit: int = Field(50, ge=1, le=500, description="Articles per outlet")
    page_size: int = Field(25, ge=1, le=100, description="Page size")
    interval_minutes: int = Field(30, ge=5, le=1440, description="Interval in minutes (5-1440)")
    max_instances: int = Field(1, ge=1, le=5, description="Max concurrent job instances")
    coalesce: bool = Field(True, description="Combine missed runs")
    misfire_grace_time: int = Field(300, ge=60, le=3600, description="Grace time for delayed starts (60-3600 seconds)")
    jitter: int = Field(10, ge=0, le=60, description="Random jitter in seconds (0-60)")
    max_retries_per_outlet: int = Field(2, ge=0, le=10, description="Max retries per outlet (0-10)")
    timeout_per_outlet: int = Field(180, ge=30, le=600, description="Timeout per outlet in seconds (30-600)")
    circuit_breaker_threshold: int = Field(5, ge=1, le=20, description="Circuit breaker threshold (1-20)")

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
    def from_article(cls, art: Article):
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
# Core Functions
# ---------------------------------------------------------------------------
async def _run_scraper(scraper_cls, keyword: str, limit: int, page_size: int) -> List[Article]:
    """Run scraper asynchronously"""
    def _blocking_call() -> List[Article]:
        scraper = scraper_cls()
        collected: List[Article] = []
        page = 1
        while len(collected) < limit:
            requested = min(page_size, limit - len(collected))
            batch = scraper.search(keyword, page=page, size=requested)
            if not batch:
                break
            collected.extend(batch)
            page += 1
        return collected[:limit]

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(EXECUTOR, _blocking_call)

async def scrape_and_populate_outlet(outlet: str, keyword: str, limit: int, page_size: int, timeout: int = 180) -> Dict[str, Any]:
    """Scrape single outlet and populate database with timeout and error handling"""
    try:
        # Get scraper class
        scraper_cls = SCRAPER_MAP[outlet]
        
        # Scrape articles with timeout
        logger.info(f"🔍 Scraping {outlet} for '{keyword}'...")
        articles = await asyncio.wait_for(
            _run_scraper(scraper_cls, keyword, limit, page_size),
            timeout=timeout
        )
        
        # Deduplicate by URL
        seen: set[str] = set()
        unique: List[Article] = []
        for art in articles:
            if art.url and art.url not in seen:
                seen.add(art.url)
                unique.append(art)
        
        # Convert to dict format for database
        article_dicts = [asdict(art) for art in unique]
        
        # Insert to database
        logger.info(f"💾 Inserting {len(article_dicts)} articles from {outlet}...")
        stats = db_service.insert_articles_to_db(article_dicts, outlet)
        
        return {
            "outlet": outlet,
            "scraped": len(articles),
            "unique": len(unique),
            "inserted": stats["inserted"],
            "duplicates_skipped": stats["duplicates_skipped"],
            "errors": stats["errors"],
            "status": "success"
        }
        
    except asyncio.TimeoutError:
        logger.error(f"⏰ Timeout scraping {outlet} after {timeout}s")
        return {
            "outlet": outlet,
            "error": f"Timeout after {timeout}s",
            "scraped": 0,
            "unique": 0,
            "inserted": 0,
            "duplicates_skipped": 0,
            "errors": 1,
            "status": "timeout"
        }
    except Exception as e:
        logger.error(f"❌ Error processing {outlet}: {e}")
        return {
            "outlet": outlet,
            "error": str(e),
            "scraped": 0,
            "unique": 0,
            "inserted": 0,
            "duplicates_skipped": 0,
            "errors": 1,
            "status": "error"
        }

async def scrape_outlet_with_retry(outlet: str, keyword: str, limit: int, page_size: int, max_retries: int = 2) -> Dict[str, Any]:
    """Scrape outlet with retry logic"""
    timeout = SCHEDULER_CONFIG.get('timeout_per_outlet', 180)
    
    for attempt in range(max_retries + 1):
        try:
            result = await scrape_and_populate_outlet(outlet, keyword, limit, page_size, timeout)
            
            # If successful, return result
            if result.get('status') == 'success':
                return result
            
            # If this is the last attempt, return the failed result
            if attempt == max_retries:
                return result
                
            # Log retry attempt
            logger.warning(f"🔄 Retrying {outlet} (attempt {attempt + 2}/{max_retries + 1})")
            await asyncio.sleep(5)  # Wait 5 seconds before retry
            
        except Exception as e:
            logger.error(f"❌ Retry attempt {attempt + 1} failed for {outlet}: {e}")
            if attempt == max_retries:
                return {
                    "outlet": outlet,
                    "error": str(e),
                    "scraped": 0,
                    "unique": 0,
                    "inserted": 0,
                    "duplicates_skipped": 0,
                    "errors": 1,
                    "status": "failed_after_retries"
                }

async def scheduled_scrape_job():
    """Enhanced scheduled scraping job with error handling and circuit breaking"""
    logger.info(f"🕐 Starting scheduled scrape at {datetime.datetime.now()}")
    
    # Initialize circuit breaker storage if not exists
    if not hasattr(scheduled_scrape_job, 'failure_counts'):
        scheduled_scrape_job.failure_counts = {}
    
    results = []
    max_retries = SCHEDULER_CONFIG.get('max_retries_per_outlet', 2)
    circuit_threshold = SCHEDULER_CONFIG.get('circuit_breaker_threshold', 5)
    
    for outlet in SCHEDULER_CONFIG['outlets']:
        # Check circuit breaker
        failure_count = scheduled_scrape_job.failure_counts.get(outlet, 0)
        if failure_count >= circuit_threshold:
            logger.warning(f"🚫 Circuit breaker: Skipping {outlet} (failed {failure_count} times)")
            results.append({
                "outlet": outlet,
                "error": f"Circuit breaker open (failed {failure_count} times)",
                "scraped": 0,
                "unique": 0,
                "inserted": 0,
                "duplicates_skipped": 0,
                "errors": 1,
                "status": "circuit_breaker_open"
            })
            continue
        
        # Scrape with retry
        result = await scrape_outlet_with_retry(
            outlet=outlet,
            keyword=SCHEDULER_CONFIG['keyword'],
            limit=SCHEDULER_CONFIG['limit'],
            page_size=SCHEDULER_CONFIG['page_size'],
            max_retries=max_retries
        )
        
        # Update circuit breaker counts
        if result.get('status') == 'success':
            scheduled_scrape_job.failure_counts[outlet] = 0  # Reset on success
        else:
            scheduled_scrape_job.failure_counts[outlet] = failure_count + 1
        
        results.append(result)
    
    # Log detailed summary
    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_duplicates = sum(r.get("duplicates_skipped", 0) for r in results)
    total_errors = sum(r.get("errors", 0) for r in results)
    successful_outlets = len([r for r in results if r.get('status') == 'success'])
    failed_outlets = len([r for r in results if r.get('status') != 'success'])
    
    logger.info(f"✅ Scheduled scrape completed: {total_inserted} inserted, {total_duplicates} duplicates, {total_errors} errors")
    logger.info(f"📊 Outlets: {successful_outlets} successful, {failed_outlets} failed")
    
    # Log failures for debugging
    for result in results:
        if result.get('status') != 'success':
            logger.warning(f"⚠️ {result['outlet']}: {result.get('error', 'Unknown error')} (status: {result.get('status')})")

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "scheduler_running": scheduler.running
    }

# Original scrape endpoint (for backwards compatibility)
@app.post("/scrape", response_model=List[ArticleModel])
async def scrape(req: ScrapeRequest):
    """Original scrape endpoint - returns articles without database storage"""
    scraper_cls = SCRAPER_MAP[req.outlet]
    articles = await _run_scraper(scraper_cls, req.keyword, req.limit, req.page_size)

    # Deduplicate by URL
    seen: set[str] = set()
    unique: List[Article] = []
    for art in articles:
        if art.url and art.url not in seen:
            seen.add(art.url)
            unique.append(art)

    return [ArticleModel.from_article(a) for a in unique]

@app.post("/scrape-and-populate")
async def scrape_and_populate(req: ScrapeAndPopulateRequest):
    """Scrape multiple outlets and populate database"""
    logger.info(f"🚀 Starting scrape and populate for {len(req.outlets)} outlets")
    
    results = []
    for outlet in req.outlets:
        result = await scrape_and_populate_outlet(
            outlet=outlet,
            keyword=req.keyword,
            limit=req.limit,
            page_size=req.page_size,
            timeout=SCHEDULER_CONFIG.get('timeout_per_outlet', 180)
        )
        results.append(result)
    
    # Calculate totals
    total_scraped = sum(r.get("scraped", 0) for r in results)
    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_duplicates = sum(r.get("duplicates_skipped", 0) for r in results)
    total_errors = sum(r.get("errors", 0) for r in results)
    
    return {
        "summary": {
            "outlets_processed": len(req.outlets),
            "total_scraped": total_scraped,
            "total_inserted": total_inserted,
            "total_duplicates": total_duplicates,
            "total_errors": total_errors
        },
        "results": results,
        "timestamp": datetime.datetime.now().isoformat()
    }

# ---------------------------------------------------------------------------
# Scheduler Endpoints
# ---------------------------------------------------------------------------

class SchedulerControlRequest(BaseModel):
    action: str = Field(..., description="Action to perform: status, start, stop, configure, trigger")
    config: Optional[SchedulerConfigRequest] = Field(None, description="Configuration for configure action")

@app.post("/scheduler")
async def scheduler_control(req: SchedulerControlRequest, background_tasks: BackgroundTasks):
    """Unified scheduler control endpoint - status, start, stop, configure, trigger"""
    global SCHEDULER_CONFIG
    
    action = req.action.lower()
    current_status = scheduler.running
    
    # Get current jobs info
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None
        })
    
    if action == "start":
        if not current_status:
            scheduler.start()
            logger.info("🟢 Scheduler started")
            message = "Scheduler started successfully"
            action_performed = "start"
        else:
            message = "Scheduler is already running"
            action_performed = "none"
    
    elif action == "stop":
        if current_status:
            scheduler.shutdown(wait=False)
            logger.info("🔴 Scheduler stopped")
            message = "Scheduler stopped successfully"
            action_performed = "stop"
        else:
            message = "Scheduler is already stopped"
            action_performed = "none"
    
    elif action == "configure":
        if req.config is None:
            raise HTTPException(status_code=400, detail="Configuration data required for configure action")
        
        config = req.config
        
        # Update configuration
        SCHEDULER_CONFIG.update({
            "outlets": config.outlets,
            "keyword": config.keyword,
            "limit": config.limit,
            "page_size": config.page_size,
            "interval_minutes": config.interval_minutes,
            "max_instances": config.max_instances,
            "coalesce": config.coalesce,
            "misfire_grace_time": config.misfire_grace_time,
            "jitter": config.jitter,
            "max_retries_per_outlet": config.max_retries_per_outlet,
            "timeout_per_outlet": config.timeout_per_outlet,
            "circuit_breaker_threshold": config.circuit_breaker_threshold
        })
        
        # Reset circuit breaker counts
        if hasattr(scheduled_scrape_job, 'failure_counts'):
            scheduled_scrape_job.failure_counts = {}
        
        # Remove existing job and add new one
        try:
            scheduler.remove_job('scheduled_scrape_job')
        except:
            pass
        
        scheduler.add_job(
            scheduled_scrape_job,
            trigger=IntervalTrigger(
                minutes=config.interval_minutes,
                jitter=config.jitter
            ),
            id='scheduled_scrape_job',
            name='Automated News Scraping',
            max_instances=config.max_instances,
            coalesce=config.coalesce,
            misfire_grace_time=config.misfire_grace_time,
            replace_existing=True
        )
        
        logger.info(f"🔧 Scheduler reconfigured: {config.interval_minutes}min intervals, {len(config.outlets)} outlets")
        logger.info(f"🔧 Enhanced settings: retries={config.max_retries_per_outlet}, timeout={config.timeout_per_outlet}s, circuit_breaker={config.circuit_breaker_threshold}")
        
        message = "Scheduler configured successfully with enhanced options"
        action_performed = "configure"
    
    elif action == "trigger":
        background_tasks.add_task(scheduled_scrape_job)
        message = "Scheduled scrape triggered manually"
        action_performed = "trigger"
    
    elif action == "status":
        message = f"Scheduler is {'running' if current_status else 'stopped'}"
        action_performed = "status"
    
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}. Use: status, start, stop, configure, trigger")
    
    # Determine available actions based on current state
    new_status = scheduler.running
    available_actions = []
    
    if new_status:
        available_actions.extend(["stop", "configure", "trigger", "status"])
    else:
        available_actions.extend(["start", "configure", "status"])
    
    return {
        "current_status": "running" if new_status else "stopped",
        "running": new_status,
        "action_performed": action_performed,
        "message": message,
        "available_actions": available_actions,
        "config": SCHEDULER_CONFIG,
        "jobs": jobs,
        "timestamp": datetime.datetime.now().isoformat(),
        "usage_examples": {
            "status": '{"action": "status"}',
            "start": '{"action": "start"}',
            "stop": '{"action": "stop"}',
            "trigger": '{"action": "trigger"}',
            "configure": '{"action": "configure", "config": {...}}'
        }
    }

# ---------------------------------------------------------------------------
# Database Statistics
# ---------------------------------------------------------------------------

@app.get("/database/stats")
async def database_stats():
    """Get database statistics"""
    try:
        article_counts = db_service.get_article_count_by_platform()
        total_articles = sum(article_counts.values())
        
        return {
            "total_articles": total_articles,
            "articles_by_platform": article_counts,
            "platforms_count": len(article_counts)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/outlets")
async def list_outlets():
    """List all available outlets"""
    return {
        "outlets": sorted(OUTLET_CHOICES),
        "total": len(OUTLET_CHOICES)
    }

# ---------------------------------------------------------------------------
# Startup/Shutdown Events
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    """Initialize scheduler on startup"""
    # Calculate start time (60 seconds from now)
    start_time = datetime.datetime.now() + datetime.timedelta(seconds=60)
    
    # Add scheduled job with delayed start
    scheduler.add_job(
        scheduled_scrape_job,
        trigger=IntervalTrigger(
            minutes=SCHEDULER_CONFIG['interval_minutes'],
            start_date=start_time,  # Start after 60 seconds
            jitter=SCHEDULER_CONFIG.get('jitter', 10)
        ),
        id='scheduled_scrape_job',
        name='Automated News Scraping',
        max_instances=SCHEDULER_CONFIG.get('max_instances', 1),
        coalesce=SCHEDULER_CONFIG.get('coalesce', True),
        misfire_grace_time=SCHEDULER_CONFIG.get('misfire_grace_time', 300),
        replace_existing=True
    )
    
    # Start scheduler
    scheduler.start()
    logger.info(f"🚀 Unified News Scraper Server started")
    logger.info(f"⏰ First scrape scheduled in 60 seconds at {start_time.strftime('%H:%M:%S')}")
    logger.info(f"🕐 Then every {SCHEDULER_CONFIG['interval_minutes']} minutes")
    logger.info(f"📰 Monitoring {len(SCHEDULER_CONFIG['outlets'])} outlets: {SCHEDULER_CONFIG['outlets']}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    scheduler.shutdown()
    EXECUTOR.shutdown(wait=True)
    logger.info("🛑 Server shutdown complete")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)