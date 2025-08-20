"""
FastAPI Dependencies

Common dependencies for API endpoints including service injection,
authentication, and request validation.
"""

from functools import lru_cache
from fastapi import Depends, HTTPException, status
from typing import Optional

from services.news_service import NewsService
from services.youtube_service import YouTubeService
from services.scheduler_service import SchedulerService
from services.database_service import UnifiedDatabaseService
from config.settings import Settings, get_settings
from core.logging import set_correlation_id, get_api_logger

logger = get_api_logger()

# Service instances (singleton pattern)
_news_service: Optional[NewsService] = None
_youtube_service: Optional[YouTubeService] = None
_scheduler_service: Optional[SchedulerService] = None
_database_service: Optional[UnifiedDatabaseService] = None


@lru_cache()
def get_settings_dependency() -> Settings:
    """Cached settings dependency"""
    return get_settings()


def get_news_service() -> NewsService:
    """Get news service instance (singleton)"""
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service


def get_youtube_service() -> YouTubeService:
    """Get YouTube service instance (singleton)"""
    global _youtube_service
    if _youtube_service is None:
        _youtube_service = YouTubeService()
    return _youtube_service


def get_scheduler_service() -> SchedulerService:
    """Get scheduler service instance (singleton)"""
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service


def get_database_service() -> UnifiedDatabaseService:
    """Get database service instance (singleton)"""
    global _database_service
    if _database_service is None:
        _database_service = UnifiedDatabaseService()
    return _database_service


def validate_outlet(outlet: str, news_service: NewsService = Depends(get_news_service)) -> str:
    """Validate that the outlet exists"""
    available_outlets = news_service.get_available_outlets()
    if outlet.lower() not in available_outlets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown outlet: {outlet}. Available outlets: {', '.join(available_outlets)}"
        )
    return outlet.lower()


def validate_outlets(outlets: list, news_service: NewsService = Depends(get_news_service)) -> list:
    """Validate that all outlets exist"""
    available_outlets = news_service.get_available_outlets()
    invalid_outlets = [outlet for outlet in outlets if outlet.lower() not in available_outlets]
    
    if invalid_outlets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown outlets: {', '.join(invalid_outlets)}. Available outlets: {', '.join(available_outlets)}"
        )
    
    return [outlet.lower() for outlet in outlets]


def validate_youtube_api_key(
    youtube_service: YouTubeService = Depends(get_youtube_service),
    settings: Settings = Depends(get_settings_dependency)
) -> str:
    """Validate that YouTube API key is configured"""
    api_key = settings.youtube_api.api_key
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="YouTube API key not configured. Please set YOUTUBE_API_KEY environment variable."
        )
    return api_key


def check_scheduler_running(scheduler_service: SchedulerService = Depends(get_scheduler_service)) -> SchedulerService:
    """Check if scheduler is running for operations that require it"""
    if not scheduler_service.is_running():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler is not running. Start the scheduler first."
        )
    return scheduler_service


def setup_request_context():
    """Setup request context with correlation ID"""
    correlation_id = set_correlation_id()
    logger.info(f"Request started with correlation ID: {correlation_id}")
    return correlation_id


# Cleanup function for application shutdown
def cleanup_services():
    """Cleanup all service instances"""
    global _news_service, _youtube_service, _scheduler_service, _database_service
    
    try:
        if _scheduler_service:
            _scheduler_service.cleanup()
        if _news_service:
            _news_service.cleanup()
        
        logger.info("Service cleanup completed")
        
    except Exception as e:
        logger.error(f"Error during service cleanup: {e}")
    
    finally:
        # Reset service instances
        _news_service = None
        _youtube_service = None
        _scheduler_service = None
        _database_service = None