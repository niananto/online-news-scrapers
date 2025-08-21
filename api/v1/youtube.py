"""
YouTube API Endpoints

REST API endpoints for YouTube channel monitoring operations including
manual scraping, channel management, and video retrieval.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import List, Dict, Any, Optional

from models.youtube import (
    YouTubeScrapeRequest, YouTubeMultiScrapeRequest, YouTubeVideoModel,
    YouTubeScrapeResponse, YouTubeChannelStatus
)
from services.youtube_service import YouTubeService
from api.dependencies import (
    get_youtube_service, setup_request_context
)
from core.logging import get_api_logger
from core.exceptions import YouTubeScrapingError, create_error_response

logger = get_api_logger()
router = APIRouter(prefix="/youtube", tags=["YouTube Monitoring"])


@router.post("/scrape", response_model=List[YouTubeVideoModel])
async def scrape_single_channel(
    request: YouTubeScrapeRequest,
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Scrape videos from a single YouTube channel
    
    This endpoint scrapes videos from the specified channel and returns them
    immediately without storing in the database. Use this for quick testing
    or when you need videos in real-time.
    """
    try:
        logger.info(f"Scraping single channel: {request.channel_handle}")
        
        # Scrape videos
        videos = await youtube_service.scrape_channel(
            channel_handle=request.channel_handle,
            max_results=request.max_results,
            published_after=request.published_after,
            published_before=request.published_before,
            keywords=request.keywords,
            hashtags=request.hashtags,
            include_comments=request.include_comments,
            include_transcripts=request.include_transcripts,
            comments_limit=request.comments_limit,
            filter_by_duration=request.filter_by_duration,
            min_duration_seconds=request.min_duration_seconds,
            max_duration_seconds=request.max_duration_seconds
        )
        
        # Convert to response models
        return [
            YouTubeVideoModel(
                video_id=video.video_id,
                title=video.title,
                description=video.description,
                channel_title=video.channel_title,
                channel_id=video.channel_id,
                channel_handle=video.channel_handle,
                published_at=video.published_at,
                thumbnail=video.thumbnail,
                view_count=video.view_count,
                like_count=video.like_count,
                comment_count=video.comment_count,
                duration=video.duration,
                duration_seconds=video.duration_seconds,
                tags=video.tags,
                video_language=video.video_language,
                comments=video.comments[:5] if video.comments else [],  # Limit for API response
                english_transcript=video.english_transcript[:500] if video.english_transcript else "",  # Truncate for API
                bengali_transcript=video.bengali_transcript[:500] if video.bengali_transcript else "",  # Truncate for API
                transcript_languages=video.transcript_languages,
                url=video.url
            )
            for video in videos
        ]
        
    except YouTubeScrapingError as e:
        logger.error(f"YouTube scraping failed: {e.message}")
        return create_error_response(e)
    except Exception as e:
        logger.error(f"Unexpected error in scrape_single_channel: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/scrape-and-store", response_model=YouTubeScrapeResponse)
async def scrape_and_store_channels(
    request: YouTubeMultiScrapeRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Scrape multiple YouTube channels and store results in database
    
    This endpoint scrapes videos from multiple channels concurrently,
    stores them in the database with deduplication, and calls the
    classification API for content analysis.
    """
    try:
        logger.info(f"Scraping and storing {len(request.channels)} channels")
        
        # Execute scraping and storage
        result = await youtube_service.scrape_multiple_channels(
            channels=request.channels,
            max_concurrent=request.max_concurrent,
            max_results=request.max_results,
            published_after=request.published_after,
            published_before=request.published_before,
            keywords=request.keywords,
            hashtags=request.hashtags,
            include_comments=request.include_comments,
            include_transcripts=request.include_transcripts,
            comments_limit=request.comments_limit,
            filter_by_duration=request.filter_by_duration,
            min_duration_seconds=request.min_duration_seconds,
            max_duration_seconds=request.max_duration_seconds
        )
        
        return YouTubeScrapeResponse(**result)
        
    except Exception as e:
        logger.error(f"Error in scrape_and_store_channels: {e}")
        raise HTTPException(status_code=500, detail=f"YouTube scraping operation failed: {str(e)}")


@router.get("/channels")
async def list_monitored_channels(
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Get list of monitored YouTube channels
    
    Returns all YouTube channels that have videos stored in the database.
    """
    try:
        channels = youtube_service.get_monitored_channels()
        return {
            "channels": channels,
            "total": len(channels),
            "description": "YouTube channels with stored videos"
        }
    except Exception as e:
        logger.error(f"Error getting monitored channels: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get channels: {str(e)}")


@router.get("/channels/status")
async def get_channel_status(
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Get status information for all YouTube channels
    
    Returns circuit breaker states, failure counts, and availability
    status for all monitored YouTube channels.
    """
    try:
        status_info = youtube_service.get_channel_status()
        
        # Convert to response models
        formatted_status = {}
        for channel, info in status_info.items():
            formatted_status[channel] = YouTubeChannelStatus(**info)
        
        return {
            "channel_status": formatted_status,
            "summary": {
                "total_channels": len(formatted_status),
                "available_channels": len([s for s in formatted_status.values() if s.available]),
                "failed_channels": len([s for s in formatted_status.values() if s.failure_count > 0])
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting channel status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get channel status: {str(e)}")


@router.get("/channels/{channel_handle}/videos")
async def get_channel_videos(
    channel_handle: str,
    limit: int = 50,
    offset: int = 0,
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Get stored videos for a specific channel
    
    Returns paginated list of videos from the specified YouTube channel
    that are stored in the database.
    """
    try:
        # Ensure channel handle has @ prefix
        if not channel_handle.startswith('@'):
            channel_handle = f'@{channel_handle}'
        
        videos = await youtube_service.get_videos_by_channel(
            channel_handle=channel_handle,
            limit=limit,
            offset=offset
        )
        
        return {
            "videos": videos,
            "channel_handle": channel_handle,
            "returned": len(videos),
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": len(videos) == limit  # Simple check
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting videos for channel {channel_handle}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get channel videos: {str(e)}")


@router.get("/quota-status")
async def get_quota_status(
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Get current quota status for all YouTube API keys
    
    Returns detailed information about API key usage, remaining quota,
    and rotation status when using multiple keys.
    """
    try:
        status = youtube_service.get_quota_status()
        return status
    except Exception as e:
        logger.error(f"Error getting quota status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get quota status: {str(e)}")


@router.post("/quota/reset")
async def reset_quota_counters(
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Force reset quota counters for all API keys
    
    This endpoint is useful for testing or when you need to manually
    reset the quota tracking. Use with caution in production.
    """
    try:
        if youtube_service.api_pool:
            youtube_service.api_pool.force_reset()
            return {"status": "success", "message": "Quota counters reset for all keys"}
        else:
            return {"status": "not_applicable", "message": "Multi-key rotation not enabled"}
    except Exception as e:
        logger.error(f"Error resetting quota: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset quota: {str(e)}")


@router.post("/channels/{channel_handle}/reset-failures")
async def reset_channel_failures(
    channel_handle: str,
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Reset failure count and circuit breaker for a specific channel
    
    Use this endpoint to manually reset the circuit breaker and failure
    count for a channel that has been marked as failing.
    """
    try:
        # Ensure channel handle has @ prefix
        if not channel_handle.startswith('@'):
            channel_handle = f'@{channel_handle}'
        
        # Reset failures
        youtube_service.reset_channel_failures(channel_handle)
        
        return {
            "message": f"Failures reset for channel: {channel_handle}",
            "channel": channel_handle,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Error resetting failures for {channel_handle}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset failures: {str(e)}")


@router.post("/reset-all-failures")
async def reset_all_channel_failures(
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Reset failure counts and circuit breakers for all channels
    
    Use this endpoint to clear all failure states and reset circuit
    breakers for all YouTube channels.
    """
    try:
        youtube_service.reset_channel_failures()
        
        return {
            "message": "All channel failures reset successfully",
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Error resetting all channel failures: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset all failures: {str(e)}")


@router.get("/videos/search")
async def search_videos(
    query: str,
    limit: int = 50,
    offset: int = 0,
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Search YouTube videos in the database
    
    Performs full-text search across video titles, descriptions, and transcripts.
    Use this to find specific videos or topics in your stored content.
    """
    try:
        # Use the database service through youtube service
        results = youtube_service.db_service.search_content(
            query=query,
            content_type="youtube",
            limit=limit
        )
        
        # Apply offset manually since it's not supported in search_content
        paginated_results = results[offset:offset + limit] if offset > 0 else results[:limit]
        
        return {
            "videos": paginated_results,
            "total_found": len(results),
            "returned": len(paginated_results),
            "query": query,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": len(results) > (offset + limit)
            }
        }
        
    except Exception as e:
        logger.error(f"Error searching videos: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/statistics")
async def get_youtube_statistics(
    _: str = Depends(setup_request_context),
    youtube_service: YouTubeService = Depends(get_youtube_service)
):
    """
    Get YouTube database statistics
    
    Returns statistics about stored YouTube videos including
    counts by channel, recent activity, language distribution, and storage metrics.
    """
    try:
        # Get YouTube-specific statistics
        youtube_stats = youtube_service.db_service.get_youtube_database_stats()
        
        return {
            "statistics": youtube_stats,
            "database_health": youtube_service.db_service.get_database_health()
        }
        
    except Exception as e:
        logger.error(f"Error getting YouTube statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")