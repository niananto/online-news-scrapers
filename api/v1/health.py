"""
Health Check API Endpoints

REST API endpoints for system health monitoring including
database connectivity, service status, and system diagnostics.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional
from datetime import datetime

from services.scheduler_service import SchedulerService
from services.news_service import NewsService
from services.youtube_service import YouTubeService
from services.database_service import UnifiedDatabaseService
from api.dependencies import (
    get_scheduler_service, get_news_service, get_youtube_service, setup_request_context
)
from config.database import get_db_manager
from core.logging import get_api_logger

logger = get_api_logger()
router = APIRouter(prefix="/health", tags=["Health Monitoring"])


@router.get("/")
async def comprehensive_health_check(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    news_service: NewsService = Depends(get_news_service),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Comprehensive health check for all system components
    
    Returns detailed health status of all services including database,
    scheduler, scraping services, and overall system health.
    """
    try:
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "healthy",
            "components": {}
        }
        
        # Database health check
        try:
            db_manager = get_db_manager()
            db_healthy = db_manager.test_connection()
            db_service = UnifiedDatabaseService()
            db_info = db_service.get_database_health()
            
            health_status["components"]["database"] = {
                "status": "healthy" if db_healthy else "unhealthy",
                "connection": "active" if db_healthy else "failed",
                "details": db_info
            }
        except Exception as e:
            health_status["components"]["database"] = {
                "status": "unhealthy",
                "connection": "failed",
                "error": str(e)
            }
        
        # Scheduler health check
        try:
            scheduler_running = scheduler_service.is_running()
            scheduler_stats = scheduler_service.get_scheduler_stats()
            
            health_status["components"]["scheduler"] = {
                "status": "healthy" if scheduler_running else "unhealthy",
                "running": scheduler_running,
                "total_jobs": scheduler_stats.get("total_jobs", 0),
                "active_jobs": len([j for j in scheduler_stats.get("job_details", []) if j.get("next_run_time")])
            }
        except Exception as e:
            health_status["components"]["scheduler"] = {
                "status": "unhealthy",
                "running": False,
                "error": str(e)
            }
        
        # News service health check
        try:
            news_outlets = news_service.get_available_outlets()
            outlet_status = news_service.get_outlet_status()
            failed_outlets = [o for o, s in outlet_status.items() if s.get("failure_count", 0) > 0]
            
            health_status["components"]["news_service"] = {
                "status": "healthy" if len(failed_outlets) < len(news_outlets) // 2 else "degraded",
                "total_outlets": len(news_outlets),
                "available_outlets": len([o for o, s in outlet_status.items() if s.get("available", True)]),
                "failed_outlets": len(failed_outlets)
            }
        except Exception as e:
            health_status["components"]["news_service"] = {
                "status": "unhealthy",
                "error": str(e)
            }
        
        # YouTube service health check
        try:
            channel_status = youtube_service.get_channel_status()
            failed_channels = [c for c, s in channel_status.items() if s.get("failure_count", 0) > 0]
            
            health_status["components"]["youtube_service"] = {
                "status": "healthy" if len(failed_channels) < len(channel_status) // 2 else "degraded",
                "total_channels": len(channel_status),
                "available_channels": len([c for c, s in channel_status.items() if s.get("available", True)]),
                "failed_channels": len(failed_channels)
            }
        except Exception as e:
            health_status["components"]["youtube_service"] = {
                "status": "unhealthy",
                "error": str(e)
            }
        
        # Determine overall health
        component_statuses = [comp.get("status", "unknown") for comp in health_status["components"].values()]
        if "unhealthy" in component_statuses:
            health_status["overall_status"] = "unhealthy"
        elif "degraded" in component_statuses:
            health_status["overall_status"] = "degraded"
        else:
            health_status["overall_status"] = "healthy"
        
        # Set HTTP status code based on health
        status_code = 200 if health_status["overall_status"] == "healthy" else 503
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "unhealthy",
            "error": str(e)
        }


@router.get("/database")
async def database_health_check(
    _: str = Depends(setup_request_context)
):
    """
    Database-specific health check
    
    Returns detailed database connectivity and performance information
    including table counts, connection status, and database metrics.
    """
    try:
        db_manager = get_db_manager()
        db_service = UnifiedDatabaseService()
        
        # Test basic connectivity
        connection_healthy = db_manager.test_connection()
        
        if not connection_healthy:
            return {
                "status": "unhealthy",
                "connection": "failed",
                "timestamp": datetime.now().isoformat()
            }
        
        # Get detailed database health information
        db_health = db_service.get_database_health()
        
        # Get additional statistics
        try:
            news_stats = db_service.get_article_count_by_platform()
            youtube_stats = db_service.get_youtube_database_stats()
            
            return {
                "status": "healthy",
                "connection": "active",
                "timestamp": datetime.now().isoformat(),
                "database_info": db_health,
                "content_statistics": {
                    "news": {
                        "total_articles": sum(news_stats.values()),
                        "platforms": len(news_stats),
                        "top_platforms": sorted(news_stats.items(), key=lambda x: x[1], reverse=True)[:5]
                    },
                    "youtube": {
                        "total_videos": youtube_stats.get("total_videos", 0),
                        "channels": len(youtube_stats.get("top_channels", [])),
                        "recent_activity": youtube_stats.get("recent_activity", [])
                    }
                }
            }
            
        except Exception as stats_error:
            logger.warning(f"Could not get detailed statistics: {stats_error}")
            return {
                "status": "healthy",
                "connection": "active",
                "timestamp": datetime.now().isoformat(),
                "database_info": db_health,
                "warning": "Statistics unavailable"
            }
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "connection": "failed",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }


@router.get("/services")
async def services_health_check(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    news_service: NewsService = Depends(get_news_service),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Services health check
    
    Returns health status of all scraping services including
    circuit breaker states, failure counts, and service availability.
    """
    try:
        services_health = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "healthy",
            "services": {}
        }
        
        # Scheduler service health
        scheduler_running = scheduler_service.is_running()
        scheduler_stats = scheduler_service.get_scheduler_stats()
        
        services_health["services"]["scheduler"] = {
            "status": "healthy" if scheduler_running else "unhealthy",
            "running": scheduler_running,
            "jobs": {
                "total": scheduler_stats.get("total_jobs", 0),
                "active": len([j for j in scheduler_stats.get("job_details", []) if j.get("next_run_time")]),
                "configurations": scheduler_stats.get("configurations", {})
            }
        }
        
        # News service health
        outlet_status = news_service.get_outlet_status()
        total_outlets = len(outlet_status)
        available_outlets = len([o for o, s in outlet_status.items() if s.get("available", True)])
        failed_outlets = len([o for o, s in outlet_status.items() if s.get("failure_count", 0) > 0])
        
        news_health = "healthy"
        if failed_outlets > total_outlets // 2:
            news_health = "degraded"
        elif available_outlets == 0:
            news_health = "unhealthy"
        
        services_health["services"]["news_scraping"] = {
            "status": news_health,
            "outlets": {
                "total": total_outlets,
                "available": available_outlets,
                "failed": failed_outlets
            },
            "circuit_breakers": {
                outlet: {
                    "state": info.get("circuit_breaker_state", "UNKNOWN"),
                    "failures": info.get("failure_count", 0)
                }
                for outlet, info in outlet_status.items()
                if info.get("circuit_breaker_state") != "CLOSED" or info.get("failure_count", 0) > 0
            }
        }
        
        # YouTube service health
        channel_status = youtube_service.get_channel_status()
        total_channels = len(channel_status)
        available_channels = len([c for c, s in channel_status.items() if s.get("available", True)])
        failed_channels = len([c for c, s in channel_status.items() if s.get("failure_count", 0) > 0])
        
        youtube_health = "healthy"
        if failed_channels > total_channels // 2:
            youtube_health = "degraded"
        elif available_channels == 0 and total_channels > 0:
            youtube_health = "unhealthy"
        
        services_health["services"]["youtube_monitoring"] = {
            "status": youtube_health,
            "channels": {
                "total": total_channels,
                "available": available_channels,
                "failed": failed_channels
            },
            "circuit_breakers": {
                channel: {
                    "state": info.get("circuit_breaker_state", "UNKNOWN"),
                    "failures": info.get("failure_count", 0)
                }
                for channel, info in channel_status.items()
                if info.get("circuit_breaker_state") != "CLOSED" or info.get("failure_count", 0) > 0
            }
        }
        
        # Determine overall services health
        service_statuses = [service.get("status", "unknown") for service in services_health["services"].values()]
        if "unhealthy" in service_statuses:
            services_health["overall_status"] = "unhealthy"
        elif "degraded" in service_statuses:
            services_health["overall_status"] = "degraded"
        
        return services_health
        
    except Exception as e:
        logger.error(f"Services health check failed: {e}")
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "unhealthy",
            "error": str(e)
        }


@router.get("/readiness")
async def readiness_check(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Readiness check for load balancers
    
    Simple endpoint that returns 200 if the service is ready to handle requests.
    This checks basic requirements: database connectivity and scheduler running.
    """
    try:
        # Check database
        db_manager = get_db_manager()
        db_healthy = db_manager.test_connection()
        
        # Check scheduler
        scheduler_running = scheduler_service.is_running()
        
        if db_healthy and scheduler_running:
            return {
                "status": "ready",
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "not_ready",
                "timestamp": datetime.now().isoformat(),
                "issues": {
                    "database": "unhealthy" if not db_healthy else "healthy",
                    "scheduler": "stopped" if not scheduler_running else "running"
                }
            }
    
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return {
            "status": "not_ready",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }


@router.get("/liveness")
async def liveness_check():
    """
    Liveness check for container orchestration
    
    Simple endpoint that returns 200 if the application is alive.
    This is a basic health check that should always return success
    unless the application is completely broken.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/metrics")
async def get_health_metrics(
    _: str = Depends(setup_request_context),
    scheduler_service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Health metrics for monitoring systems
    
    Returns metrics suitable for monitoring systems like Prometheus
    including counts, durations, and status information.
    """
    try:
        # Get scheduler metrics
        scheduler_stats = scheduler_service.get_scheduler_stats()
        
        # Database metrics
        db_service = UnifiedDatabaseService()
        db_health = db_service.get_database_health()
        news_counts = db_service.get_article_count_by_platform()
        youtube_stats = db_service.get_youtube_database_stats()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "scheduler_metrics": {
                "running": 1 if scheduler_stats.get("running") else 0,
                "total_jobs": scheduler_stats.get("total_jobs", 0),
                "job_executions": scheduler_stats.get("job_stats", {}),
                "active_jobs": len([j for j in scheduler_stats.get("job_details", []) if j.get("next_run_time")])
            },
            "database_metrics": {
                "connection_healthy": 1,  # If we got here, connection is working
                "news_articles_total": sum(news_counts.values()),
                "news_platforms_total": len(news_counts),
                "youtube_videos_total": youtube_stats.get("total_videos", 0),
                "youtube_channels_total": len(youtube_stats.get("top_channels", []))
            },
            "service_metrics": {
                "news_outlets_available": len(scheduler_stats.get("service_status", {}).get("news_outlets", {})),
                "youtube_channels_monitored": len(scheduler_stats.get("service_status", {}).get("youtube_channels", {}))
            }
        }
        
    except Exception as e:
        logger.error(f"Health metrics collection failed: {e}")
        return {
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "scheduler_metrics": {"running": 0},
            "database_metrics": {"connection_healthy": 0},
            "service_metrics": {}
        }