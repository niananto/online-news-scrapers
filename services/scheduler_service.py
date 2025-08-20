"""
Unified Scheduler Service

Centralized scheduler management for both news and YouTube scraping jobs
with advanced job control, monitoring, and error handling.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job
from dotenv import load_dotenv

# Load environment variables from .env file before importing settings
load_dotenv()

from services.news_service import NewsService
from services.youtube_service import YouTubeService
from core.logging import get_scheduler_logger, log_performance
from core.exceptions import SchedulerError
from config.settings import get_settings

logger = get_scheduler_logger()


class SchedulerService:
    """
    Unified scheduler service managing both news and YouTube scraping jobs
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.scheduler = AsyncIOScheduler()
        self.news_service = NewsService()
        self.youtube_service = YouTubeService()
        
        # Job tracking
        self.job_stats = {}
        self.last_run_times = {}
        self.next_run_times = {}
        
        # Job configurations
        self.news_config = self.settings.news_scheduler
        self.youtube_config = self.settings.youtube_scheduler
        
        logger.info("Scheduler service initialized")
    
    # =============================================================================
    # Scheduler Lifecycle Management
    # =============================================================================
    
    def start(self):
        """Start the scheduler"""
        try:
            if not self.scheduler.running:
                self.scheduler.start()
                logger.info("🟢 Scheduler started successfully")
            else:
                logger.info("Scheduler is already running")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise SchedulerError("start", str(e))
    
    def stop(self, wait: bool = True):
        """Stop the scheduler"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=wait)
                logger.info("🔴 Scheduler stopped")
            else:
                logger.info("Scheduler is already stopped")
        except Exception as e:
            logger.error(f"Failed to stop scheduler: {e}")
            raise SchedulerError("stop", str(e))
    
    def is_running(self) -> bool:
        """Check if scheduler is running"""
        return self.scheduler.running
    
    # =============================================================================
    # Job Configuration and Management
    # =============================================================================
    
    def configure_news_jobs(
        self,
        outlets: List[str] = None,
        keyword: str = None,
        limit: int = None,
        page_size: int = None,
        interval_minutes: int = None,
        **kwargs
    ):
        """
        Configure news scraping jobs with updated parameters
        
        Args:
            outlets: List of news outlets to scrape
            keyword: Search keyword
            limit: Articles per outlet
            page_size: Articles per page
            interval_minutes: Scraping interval in minutes
            **kwargs: Additional scheduler options
        """
        try:
            # Update configuration
            if outlets is not None:
                self.news_config.outlets = outlets
            if keyword is not None:
                self.news_config.keyword = keyword
            if limit is not None:
                self.news_config.limit = limit
            if page_size is not None:
                self.news_config.page_size = page_size
            if interval_minutes is not None:
                self.news_config.interval_minutes = interval_minutes
            
            # Update other options
            for key, value in kwargs.items():
                if hasattr(self.news_config, key):
                    setattr(self.news_config, key, value)
            
            # Remove existing news job
            self._remove_job('news_scraping_job')
            
            # Add new job with updated configuration
            self.scheduler.add_job(
                self._scheduled_news_job,
                trigger=IntervalTrigger(
                    minutes=self.news_config.interval_minutes,
                    jitter=self.news_config.jitter
                ),
                id='news_scraping_job',
                name='Automated News Scraping',
                max_instances=self.news_config.max_instances,
                coalesce=self.news_config.coalesce,
                misfire_grace_time=self.news_config.misfire_grace_time,
                replace_existing=True
            )
            
            logger.info(f"[REFRESH] News jobs configured: {len(self.news_config.outlets)} outlets, "
                       f"{self.news_config.interval_minutes}min intervals")
            
        except Exception as e:
            logger.error(f"Failed to configure news jobs: {e}")
            raise SchedulerError("configure_news", str(e))
    
    def configure_youtube_jobs(
        self,
        channels: List[str] = None,
        max_results_per_channel: int = None,
        keywords: List[str] = None,
        interval_minutes: int = None,
        enabled: bool = None,
        **kwargs
    ):
        """
        Configure YouTube scraping jobs with updated parameters
        
        Args:
            channels: List of YouTube channel handles
            max_results_per_channel: Max videos per channel
            keywords: Keywords for filtering
            interval_minutes: Scraping interval in minutes
            enabled: Whether YouTube monitoring is enabled
            **kwargs: Additional options
        """
        try:
            # Update configuration
            if channels is not None:
                self.youtube_config.channels = channels
            if max_results_per_channel is not None:
                self.youtube_config.max_results_per_channel = max_results_per_channel
            if keywords is not None:
                self.youtube_config.keywords = keywords
            if interval_minutes is not None:
                self.youtube_config.interval_minutes = interval_minutes
            if enabled is not None:
                self.youtube_config.enabled = enabled
            
            # Update other options
            for key, value in kwargs.items():
                if hasattr(self.youtube_config, key):
                    setattr(self.youtube_config, key, value)
            
            # Remove existing YouTube job
            self._remove_job('youtube_scraping_job')
            
            # Add new job if enabled
            if self.youtube_config.enabled:
                self.scheduler.add_job(
                    self._scheduled_youtube_job,
                    trigger=IntervalTrigger(minutes=self.youtube_config.interval_minutes),
                    id='youtube_scraping_job',
                    name='YouTube Channel Monitoring',
                    max_instances=self.youtube_config.max_instances,
                    coalesce=self.youtube_config.coalesce,
                    misfire_grace_time=self.youtube_config.misfire_grace_time,
                    replace_existing=True
                )
                
                logger.info(f"[REFRESH] YouTube jobs configured: {len(self.youtube_config.channels)} channels, "
                           f"{self.youtube_config.interval_minutes}min intervals")
            else:
                logger.info("[REFRESH] YouTube monitoring disabled")
            
        except Exception as e:
            logger.error(f"Failed to configure YouTube jobs: {e}")
            raise SchedulerError("configure_youtube", str(e))
    
    def setup_default_jobs(self):
        """Setup default jobs based on current configuration"""
        logger.info("Setting up default scheduler jobs...")
        
        # Setup news scraping job
        news_start_time = datetime.now() + timedelta(seconds=30)
        self.scheduler.add_job(
            self._scheduled_news_job,
            trigger=IntervalTrigger(
                minutes=self.news_config.interval_minutes,
                start_date=news_start_time,
                jitter=self.news_config.jitter
            ),
            id='news_scraping_job',
            name='Automated News Scraping',
            max_instances=self.news_config.max_instances,
            coalesce=self.news_config.coalesce,
            misfire_grace_time=self.news_config.misfire_grace_time
        )
        
        # Setup YouTube scraping job if enabled
        if self.youtube_config.enabled:
            youtube_start_time = datetime.now() + timedelta(seconds=60)  # Start 2 minutes later
            self.scheduler.add_job(
                self._scheduled_youtube_job,
                trigger=IntervalTrigger(
                    minutes=self.youtube_config.interval_minutes,
                    start_date=youtube_start_time,
                    jitter=10
                ),
                id='youtube_scraping_job',
                name='YouTube Channel Monitoring',
                max_instances=self.youtube_config.max_instances,
                coalesce=self.youtube_config.coalesce,
                misfire_grace_time=self.youtube_config.misfire_grace_time
            )
            
            logger.info(f"[TV] YouTube monitoring scheduled to start at {youtube_start_time.strftime('%H:%M:%S')}")
        else:
            logger.info("[TV] YouTube monitoring is disabled")
        
        logger.info(f"[TIME] News scraping scheduled to start at {news_start_time.strftime('%H:%M:%S')}")
        logger.info(f"📰 Monitoring {len(self.news_config.outlets)} news outlets")
        logger.info(f"[TV] Monitoring {len(self.youtube_config.channels)} YouTube channels")
    
    # =============================================================================
    # Job Execution and Monitoring
    # =============================================================================
    
    async def trigger_news_scraping(self) -> Dict[str, Any]:
        """Manually trigger news scraping job"""
        logger.info("[REFRESH] Manually triggering news scraping...")
        try:
            result = await self._scheduled_news_job()
            return {"status": "success", "message": "News scraping completed", "result": result}
        except Exception as e:
            logger.error(f"Manual news scraping failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def trigger_youtube_scraping(self) -> Dict[str, Any]:
        """Manually trigger YouTube scraping job"""
        logger.info("[REFRESH] Manually triggering YouTube scraping...")
        try:
            result = await self._scheduled_youtube_job()
            return {"status": "success", "message": "YouTube scraping completed", "result": result}
        except Exception as e:
            logger.error(f"Manual YouTube scraping failed: {e}")
            return {"status": "error", "message": str(e)}
    
    def get_job_status(self, job_id: str = None) -> Dict[str, Any]:
        """
        Get status of specific job or all jobs
        
        Args:
            job_id: Specific job ID or None for all jobs
            
        Returns:
            Dictionary with job status information
        """
        if job_id:
            job = self.scheduler.get_job(job_id)
            if job:
                return self._format_job_info(job)
            else:
                return {"error": f"Job {job_id} not found"}
        else:
            # Return all jobs
            jobs = {}
            for job in self.scheduler.get_jobs():
                jobs[job.id] = self._format_job_info(job)
            return jobs
    
    def get_scheduler_stats(self) -> Dict[str, Any]:
        """Get comprehensive scheduler statistics"""
        jobs = self.scheduler.get_jobs()
        
        return {
            "running": self.scheduler.running,
            "total_jobs": len(jobs),
            "job_details": [self._format_job_info(job) for job in jobs],
            "configurations": {
                "news": {
                    "outlets_count": len(self.news_config.outlets),
                    "interval_minutes": self.news_config.interval_minutes,
                    "keyword": self.news_config.keyword,
                    "limit": self.news_config.limit
                },
                "youtube": {
                    "channels_count": len(self.youtube_config.channels),
                    "interval_minutes": self.youtube_config.interval_minutes,
                    "enabled": self.youtube_config.enabled,
                    "max_results_per_channel": self.youtube_config.max_results_per_channel
                }
            },
            "job_stats": self.job_stats.copy(),
            "service_status": {
                "news_outlets": self.news_service.get_outlet_status(),
                "youtube_channels": self.youtube_service.get_channel_status()
            }
        }
    
    # =============================================================================
    # Scheduled Job Implementations
    # =============================================================================
    
    async def _scheduled_news_job(self) -> Optional[Dict[str, Any]]:
        """Execute scheduled news scraping job"""
        job_id = 'news_scraping_job'
        start_time = datetime.now()
        
        logger.info(f"[TIME] Starting scheduled news scraping at {start_time}")
        
        try:
            with log_performance(logger, "scheduled news scraping"):
                # Execute news scraping
                result = await self.news_service.scrape_multiple_outlets(
                    outlets=self.news_config.outlets,
                    keyword=self.news_config.keyword,
                    limit=self.news_config.limit,
                    page_size=self.news_config.page_size,
                    max_concurrent=3
                )
                
                # Update job statistics
                self._update_job_stats(job_id, start_time, result.get('summary', {}))
                
                # Log summary
                summary = result.get('summary', {})
                logger.info(f"📅 Scheduled news scraping complete: {summary.get('total_inserted', 0)} articles, {summary.get('successful_outlets', 0)} successful outlets, next run in {self.news_config.interval_minutes} minutes")
                
                return result
                
        except Exception as e:
            logger.error(f"[ERROR] Scheduled news scraping failed: {e}")
            self._update_job_stats(job_id, start_time, {}, error=str(e))
            return None
    
    async def _scheduled_youtube_job(self) -> Optional[Dict[str, Any]]:
        """Execute scheduled YouTube scraping job"""
        if not self.youtube_config.enabled:
            logger.info("[TV] YouTube scheduled monitoring is disabled")
            return None
        
        job_id = 'youtube_scraping_job'
        start_time = datetime.now()
        
        logger.info(f"[TV] Starting scheduled YouTube monitoring at {start_time}")
        
        try:
            with log_performance(logger, "scheduled YouTube scraping"):
                # Calculate date range if enabled
                kwargs = {
                    "max_results": self.youtube_config.max_results_per_channel,
                    "keywords": self.youtube_config.keywords,
                    "hashtags": self.youtube_config.hashtags,
                    "include_comments": self.youtube_config.include_comments,
                    "include_transcripts": self.youtube_config.include_transcripts,
                    "comments_limit": self.youtube_config.comments_limit,
                    "filter_by_duration": self.youtube_config.filter_by_duration,
                    "min_duration_seconds": self.youtube_config.min_duration_seconds,
                    "max_duration_seconds": self.youtube_config.max_duration_seconds
                }
                
                if self.youtube_config.use_date_range:
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=self.youtube_config.days_back)
                    
                    kwargs.update({
                        "published_after": start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "published_before": end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
                    })
                    
                    logger.info(f"📅 Filtering videos from last {self.youtube_config.days_back} days")
                
                # Execute YouTube scraping
                result = await self.youtube_service.scrape_multiple_channels(
                    channels=self.youtube_config.channels,
                    max_concurrent=2,
                    **kwargs
                )
                
                # Update job statistics
                self._update_job_stats(job_id, start_time, result.get('summary', {}))
                
                # Log summary
                summary = result.get('summary', {})
                logger.info(f"[OK] Scheduled YouTube monitoring completed: "
                           f"{summary.get('total_stored', 0)} videos stored, "
                           f"{summary.get('successful_channels', 0)} channels successful")
                
                return result
                
        except Exception as e:
            logger.error(f"[ERROR] Scheduled YouTube monitoring failed: {e}")
            self._update_job_stats(job_id, start_time, {}, error=str(e))
            return None
    
    # =============================================================================
    # Helper Methods
    # =============================================================================
    
    def _remove_job(self, job_id: str):
        """Safely remove a job"""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job: {job_id}")
        except Exception:
            pass  # Job might not exist
    
    def _format_job_info(self, job: Job) -> Dict[str, Any]:
        """Format job information for API response"""
        return {
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
            "max_instances": getattr(job, 'max_instances', None),
            "coalesce": getattr(job, 'coalesce', None),
            "misfire_grace_time": getattr(job, 'misfire_grace_time', None)
        }
    
    def _update_job_stats(
        self,
        job_id: str,
        start_time: datetime,
        summary: Dict[str, Any],
        error: str = None
    ):
        """Update job execution statistics"""
        duration = (datetime.now() - start_time).total_seconds()
        
        if job_id not in self.job_stats:
            self.job_stats[job_id] = {
                "total_runs": 0,
                "successful_runs": 0,
                "failed_runs": 0,
                "total_duration": 0,
                "average_duration": 0,
                "last_run_time": None,
                "last_error": None
            }
        
        stats = self.job_stats[job_id]
        stats["total_runs"] += 1
        stats["total_duration"] += duration
        stats["average_duration"] = stats["total_duration"] / stats["total_runs"]
        stats["last_run_time"] = start_time.isoformat()
        
        if error:
            stats["failed_runs"] += 1
            stats["last_error"] = error
        else:
            stats["successful_runs"] += 1
            stats["last_error"] = None
        
        # Store summary data if available
        if summary:
            stats["last_summary"] = summary
    
    def cleanup(self):
        """Cleanup scheduler resources"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            self.news_service.cleanup()
            logger.info("Scheduler service cleaned up")
        except Exception as e:
            logger.error(f"Error during scheduler cleanup: {e}")
    
    def reset_job_failures(self):
        """Reset failure counts for all services"""
        self.news_service.reset_outlet_failures()
        self.youtube_service.reset_channel_failures()
        logger.info("Reset all job failures")