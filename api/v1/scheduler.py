"""
Scheduler API Endpoints

REST API endpoints for scheduler management including job control,
configuration updates, and monitoring of automated scraping operations.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional

from models.scheduler import (
    SchedulerConfigRequest, NewsSchedulerConfig, YouTubeSchedulerConfig,
    SchedulerStatusResponse, JobTriggerResponse
)
from services.scheduler_service import SchedulerService
from api.dependencies import get_scheduler_service, setup_request_context
from core.logging import get_api_logger
from core.exceptions import SchedulerError

logger = get_api_logger()
router = APIRouter(prefix="/scheduler", tags=["Scheduler Management"])


@router.get("/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Get comprehensive scheduler status and job information
    
    Returns detailed information about the scheduler state, running jobs,
    job statistics, and service health status.
    """
    try:
        stats = scheduler_service.get_scheduler_stats()
        
        return SchedulerStatusResponse(
            running=stats["running"],
            total_jobs=stats["total_jobs"],
            job_details=stats["job_details"],
            configurations=stats["configurations"],
            job_stats=stats["job_stats"],
            service_status=stats["service_status"]
        )
        
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get scheduler status: {str(e)}")


@router.post("/configure/news")
async def configure_news_scheduler(
    config: NewsSchedulerConfig,
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Update news scheduler configuration
    
    Reconfigure the news scraping jobs with new parameters including
    outlets, keywords, intervals, and other settings. Changes take
    effect immediately without requiring a restart.
    """
    try:
        logger.info(f"Updating news scheduler configuration")
        
        scheduler_service.configure_news_jobs(
            outlets=config.outlets,
            keyword=config.keyword,
            limit=config.limit,
            page_size=config.page_size,
            interval_minutes=config.interval_minutes,
            max_instances=config.max_instances,
            coalesce=config.coalesce,
            jitter=config.jitter,
            misfire_grace_time=config.misfire_grace_time
        )
        
        return {
            "message": "News scheduler configuration updated successfully",
            "configuration": config.dict(),
            "status": "success",
            "next_run": scheduler_service.get_job_status("news_scraping_job")
        }
        
    except SchedulerError as e:
        logger.error(f"Scheduler configuration failed: {e.message}")
        raise HTTPException(status_code=400, detail=f"Configuration error: {e.message}")
    except Exception as e:
        logger.error(f"Error configuring news scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to configure scheduler: {str(e)}")


@router.post("/configure/youtube")
async def configure_youtube_scheduler(
    config: YouTubeSchedulerConfig,
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Update YouTube scheduler configuration
    
    Reconfigure the YouTube monitoring jobs with new parameters including
    channels, intervals, filters, and other settings. Changes take
    effect immediately without requiring a restart.
    """
    try:
        logger.info(f"Updating YouTube scheduler configuration")
        
        scheduler_service.configure_youtube_jobs(
            channels=config.channels,
            max_results_per_channel=config.max_results_per_channel,
            keywords=config.keywords,
            interval_minutes=config.interval_minutes,
            enabled=config.enabled,
            max_instances=config.max_instances,
            coalesce=config.coalesce,
            misfire_grace_time=config.misfire_grace_time,
            use_date_range=config.use_date_range,
            days_back=config.days_back,
            hashtags=config.hashtags,
            include_comments=config.include_comments,
            include_transcripts=config.include_transcripts,
            comments_limit=config.comments_limit,
            filter_by_duration=config.filter_by_duration,
            min_duration_seconds=config.min_duration_seconds,
            max_duration_seconds=config.max_duration_seconds
        )
        
        return {
            "message": "YouTube scheduler configuration updated successfully",
            "configuration": config.dict(),
            "status": "success",
            "next_run": scheduler_service.get_job_status("youtube_scraping_job") if config.enabled else "disabled"
        }
        
    except SchedulerError as e:
        logger.error(f"Scheduler configuration failed: {e.message}")
        raise HTTPException(status_code=400, detail=f"Configuration error: {e.message}")
    except Exception as e:
        logger.error(f"Error configuring YouTube scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to configure scheduler: {str(e)}")


@router.post("/trigger/news", response_model=JobTriggerResponse)
async def trigger_news_scraping(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Manually trigger news scraping job
    
    Immediately execute the news scraping job without waiting for the
    scheduled time. This runs all configured news outlets.
    """
    try:
        logger.info("Manually triggering news scraping job")
        
        result = await scheduler_service.trigger_news_scraping()
        
        return JobTriggerResponse(
            job_type="news_scraping",
            status=result["status"],
            message=result["message"],
            result=result.get("result")
        )
        
    except Exception as e:
        logger.error(f"Error triggering news scraping: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger news scraping: {str(e)}")


@router.post("/trigger/youtube", response_model=JobTriggerResponse)
async def trigger_youtube_scraping(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Manually trigger YouTube scraping job
    
    Immediately execute the YouTube monitoring job without waiting for the
    scheduled time. This runs all configured YouTube channels.
    """
    try:
        logger.info("Manually triggering YouTube scraping job")
        
        result = await scheduler_service.trigger_youtube_scraping()
        
        return JobTriggerResponse(
            job_type="youtube_scraping",
            status=result["status"],
            message=result["message"],
            result=result.get("result")
        )
        
    except Exception as e:
        logger.error(f"Error triggering YouTube scraping: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger YouTube scraping: {str(e)}")


@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Get status of a specific scheduled job
    
    Returns detailed information about a specific job including
    next run time, trigger configuration, and execution history.
    """
    try:
        job_info = scheduler_service.get_job_status(job_id)
        
        if "error" in job_info:
            raise HTTPException(status_code=404, detail=job_info["error"])
        
        return {
            "job_id": job_id,
            "job_info": job_info,
            "status": "found"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status for {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@router.get("/jobs")
async def list_all_jobs(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Get status of all scheduled jobs
    
    Returns information about all active jobs in the scheduler
    including their configurations and next run times.
    """
    try:
        all_jobs = scheduler_service.get_job_status()
        
        return {
            "jobs": all_jobs,
            "total_jobs": len(all_jobs),
            "scheduler_running": scheduler_service.is_running()
        }
        
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


@router.post("/start")
async def start_scheduler(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Start the scheduler
    
    Start the scheduler if it's not already running. All configured
    jobs will begin executing according to their schedules.
    """
    try:
        if scheduler_service.is_running():
            return {
                "message": "Scheduler is already running",
                "status": "already_running"
            }
        
        scheduler_service.start()
        
        return {
            "message": "Scheduler started successfully",
            "status": "started"
        }
        
    except SchedulerError as e:
        logger.error(f"Failed to start scheduler: {e.message}")
        raise HTTPException(status_code=400, detail=f"Scheduler error: {e.message}")
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {str(e)}")


@router.post("/stop")
async def stop_scheduler(
    wait: bool = True,
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Stop the scheduler
    
    Stop the scheduler and all running jobs. Use the 'wait' parameter
    to control whether to wait for currently executing jobs to finish.
    """
    try:
        if not scheduler_service.is_running():
            return {
                "message": "Scheduler is already stopped",
                "status": "already_stopped"
            }
        
        scheduler_service.stop(wait=wait)
        
        return {
            "message": f"Scheduler stopped successfully (wait={wait})",
            "status": "stopped"
        }
        
    except SchedulerError as e:
        logger.error(f"Failed to stop scheduler: {e.message}")
        raise HTTPException(status_code=400, detail=f"Scheduler error: {e.message}")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {str(e)}")


@router.post("/reset-failures")
async def reset_job_failures(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Reset failure counts for all scraping services
    
    Clear all failure states and reset circuit breakers for both
    news outlets and YouTube channels. Use this to recover from
    widespread failures.
    """
    try:
        scheduler_service.reset_job_failures()
        
        return {
            "message": "All job failures reset successfully",
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Error resetting job failures: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset failures: {str(e)}")


@router.get("/health")
async def get_scheduler_health(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Get scheduler health information
    
    Returns basic health status of the scheduler including
    running state and job execution statistics.
    """
    try:
        stats = scheduler_service.get_scheduler_stats()
        
        # Simple health calculation
        is_healthy = (
            stats["running"] and 
            stats["total_jobs"] > 0 and
            len([job for job in stats["job_details"] if job.get("next_run_time")]) > 0
        )
        
        return {
            "status": "healthy" if is_healthy else "degraded",
            "running": stats["running"],
            "total_jobs": stats["total_jobs"],
            "active_jobs": len([job for job in stats["job_details"] if job.get("next_run_time")]),
            "job_execution_stats": stats["job_stats"]
        }
        
    except Exception as e:
        logger.error(f"Error getting scheduler health: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }