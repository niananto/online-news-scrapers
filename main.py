"""
Unified Scraping Service - Main Application

FastAPI application entry point for the unified news and YouTube scraping service.
Provides comprehensive scraping automation with scheduling, monitoring, and API access.

Features:
- Unified news and YouTube scraping
- Automated scheduling with circuit breakers
- Database storage with deduplication
- Classification API integration
- Comprehensive monitoring and health checks
- Production-ready error handling and logging

Run with:
    python main.py
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file before importing settings
load_dotenv()

# Core imports
from config.settings import get_settings
from config.database import get_db_manager
from core.logging import setup_logging, get_logger
from core.exceptions import (
    ScrapingServiceException, scraping_service_exception_handler,
    general_exception_handler
)
from core.middleware import (
    CorrelationIdMiddleware, LoggingMiddleware, SecurityHeadersMiddleware,
    RateLimitMiddleware, MetricsMiddleware
)

# Service imports
from services.scheduler_service import SchedulerService

# API imports
from api.dependencies import cleanup_services, get_scheduler_service
from api.v1.news import router as news_router
from api.v1.youtube import router as youtube_router
from api.v1.scheduler import router as scheduler_router
from api.v1.health import router as health_router

# Initialize settings and logging
settings = get_settings()
setup_logging(
    log_level=settings.app.log_level,
    json_logs=not settings.app.console_logging,
    readable_logs=settings.app.console_logging,
    log_file=settings.app.log_file
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager for startup and shutdown operations
    
    This handles proper initialization and cleanup of services, database
    connections, and scheduled jobs.
    """
    logger.info("[START] Starting Unified Scraping Service...")
    
    # Startup operations
    try:
        # Initialize database connection pool
        db_manager = get_db_manager()
        db_manager.initialize_pool(min_connections=2, max_connections=10)
        logger.info("[OK] Database connection pool initialized")
        
        # Test database connectivity
        if db_manager.test_connection():
            logger.info("[OK] Database connectivity verified")
        else:
            logger.error("[ERROR] Database connectivity test failed")
            raise Exception("Database connection failed")
        
        # Initialize scheduler service
        scheduler_service = get_scheduler_service()
        
        # Setup default scheduled jobs
        scheduler_service.setup_default_jobs()
        
        # Start the scheduler
        scheduler_service.start()
        logger.info("[OK] Scheduler service started")
        
        # Log configuration summary
        logger.info(f"[LIST] Configuration Summary:")
        logger.info(f"   📰 News outlets: {len(settings.news_scheduler.outlets)}")
        logger.info(f"   [TV] YouTube channels: {len(settings.youtube_scheduler.channels)}")
        logger.info(f"   [TIME] News interval: {settings.news_scheduler.interval_minutes} minutes")
        logger.info(f"   [TIME] YouTube interval: {settings.youtube_scheduler.interval_minutes} minutes")
        logger.info(f"   [WEB] API URL: http://{settings.app.host}:{settings.app.port}")
        
        logger.info("🎉 Unified Scraping Service startup completed successfully!")
        
        yield
        
    except Exception as e:
        logger.error(f"[ERROR] Startup failed: {e}")
        raise
    
    # Shutdown operations
    finally:
        logger.info("🛑 Shutting down Unified Scraping Service...")
        
        try:
            # Cleanup services
            cleanup_services()
            
            # Close database connections
            db_manager.close_pool()
            logger.info("[OK] Database connections closed")
            
            logger.info("[OK] Shutdown completed successfully")
            
        except Exception as e:
            logger.error(f"[ERROR] Shutdown error: {e}")


# Create FastAPI application
app = FastAPI(
    title=settings.app.app_name,
    version="1.0.0",
    description="""
    Unified News and YouTube Scraping Service
    
    A comprehensive scraping automation system that provides:
    
    ## Features
    - **Automated News Scraping**: 26+ news outlets with keyword search
    - **YouTube Channel Monitoring**: Video, transcript, and comment extraction  
    - **Intelligent Scheduling**: Circuit breakers, retry logic, rate limiting
    - **Database Storage**: PostgreSQL with deduplication and full-text search
    - **Classification Integration**: Automatic content classification via API
    - **Comprehensive Monitoring**: Health checks, metrics, and status tracking
    
    ## API Documentation
    - **News API**: `/api/v1/news/` - Manual and automated news scraping
    - **YouTube API**: `/api/v1/youtube/` - Channel monitoring and video analysis
    - **Scheduler API**: `/api/v1/scheduler/` - Job control and configuration
    - **Health API**: `/api/v1/health/` - System health and diagnostics
    
    ## Getting Started
    1. Check system health: `GET /api/v1/health`
    2. View available outlets: `GET /api/v1/news/outlets`
    3. Monitor scheduler status: `GET /api/v1/scheduler/status`
    4. Trigger manual scraping: `POST /api/v1/news/scrape-and-store`
    
    The system runs automated scraping jobs based on configured schedules.
    All operations are logged and can be monitored through the API endpoints.
    """,
    docs_url=settings.app.docs_url,
    redoc_url=settings.app.redoc_url,
    lifespan=lifespan
)

# Add middleware (order matters - first added is outermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=120)  # Adjust as needed
app.add_middleware(MetricsMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Add exception handlers
app.add_exception_handler(ScrapingServiceException, scraping_service_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Include API routers
app.include_router(news_router, prefix=settings.app.api_v1_prefix)
app.include_router(youtube_router, prefix=settings.app.api_v1_prefix)
app.include_router(scheduler_router, prefix=settings.app.api_v1_prefix)
app.include_router(health_router, prefix=settings.app.api_v1_prefix)


# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint providing service information and quick links
    """
    return {
        "service": settings.app.app_name,
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "documentation": {
            "interactive_docs": f"http://{settings.app.host}:{settings.app.port}{settings.app.docs_url}",
            "redoc": f"http://{settings.app.host}:{settings.app.port}{settings.app.redoc_url}"
        },
        "api_endpoints": {
            "news": f"{settings.app.api_v1_prefix}/news/",
            "youtube": f"{settings.app.api_v1_prefix}/youtube/",
            "scheduler": f"{settings.app.api_v1_prefix}/scheduler/",
            "health": f"{settings.app.api_v1_prefix}/health/"
        },
        "quick_start": {
            "health_check": f"{settings.app.api_v1_prefix}/health",
            "available_outlets": f"{settings.app.api_v1_prefix}/news/outlets",
            "scheduler_status": f"{settings.app.api_v1_prefix}/scheduler/status"
        }
    }


# Basic health check endpoint (separate from full health API)
@app.get("/health")
async def basic_health_check():
    """
    Basic health check endpoint for load balancers and monitoring
    """
    try:
        # Quick health check
        db_manager = get_db_manager()
        db_healthy = db_manager.test_connection()
        
        scheduler_service = get_scheduler_service()
        scheduler_running = scheduler_service.is_running()
        
        return {
            "status": "healthy" if db_healthy and scheduler_running else "degraded",
            "timestamp": datetime.now().isoformat(),
            "checks": {
                "database": "healthy" if db_healthy else "unhealthy",
                "scheduler": "running" if scheduler_running else "stopped"
            }
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }
        )


# Metrics endpoint for monitoring
@app.get("/metrics")
async def get_metrics():
    """
    Basic metrics endpoint for monitoring and observability
    """
    try:
        # Get metrics from middleware if available
        metrics = {}
        
        # Check if MetricsMiddleware is available
        for middleware in app.user_middleware:
            if hasattr(middleware.cls, 'get_metrics'):
                metrics = middleware.cls.get_metrics()
                break
        
        # Add service-specific metrics
        scheduler_service = get_scheduler_service()
        scheduler_stats = scheduler_service.get_scheduler_stats()
        
        return {
            "http_metrics": metrics,
            "scheduler_metrics": {
                "running": scheduler_stats["running"],
                "total_jobs": scheduler_stats["total_jobs"],
                "job_stats": scheduler_stats["job_stats"]
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "error": "Metrics collection failed",
                "timestamp": datetime.now().isoformat()
            }
        )


if __name__ == "__main__":
    """
    Development server entry point
    
    For production, use a proper ASGI server like uvicorn or gunicorn:
        uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
    """
    logger.info("Starting development server...")
    
    uvicorn.run(
        "main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=settings.app.reload,
        log_level=settings.app.log_level.lower(),
        access_log=True
    )