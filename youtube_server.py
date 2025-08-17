from __future__ import annotations

"""YouTube Content Monitoring Server

Dedicated FastAPI server for YouTube channel monitoring, transcript extraction, 
and content analysis with automated scheduling.

Run with::
    python youtube_server.py
    uvicorn youtube_server:app --reload --port 8001

Features:
- YouTube channel scraping with Data API v3
- Video transcript extraction (English/Bengali)
- Comment extraction and analysis
- Automated scheduling with configurable intervals
- Database storage with deduplication
- Content analysis and statistics
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import List, Optional, Dict, Any
import datetime
import os
from dotenv import load_dotenv
import aiohttp

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Import YouTube components
from youtube_scrapers.channel_scraper import YouTubeChannelScraper
from youtube_scrapers.base import YouTubeVideo
from youtube_database_service import YouTubeDatabaseService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Thread pool and services
EXECUTOR = ThreadPoolExecutor(max_workers=2)
youtube_db_service = YouTubeDatabaseService()
scheduler = AsyncIOScheduler()

# YouTube Classification API Configuration
YOUTUBE_CLASSIFICATION_API_URL = os.getenv('YOUTUBE_CLASSIFICATION_API_URL', 'http://localhost:8000/api/v1/youtube/classify-batch')
YOUTUBE_CLASSIFICATION_API_TIMEOUT = int(os.getenv('YOUTUBE_CLASSIFICATION_API_TIMEOUT', '30000'))

# FastAPI app
app = FastAPI(
    title="YouTube Content Monitoring API", 
    version="1.0.0", 
    description="YouTube channel monitoring for content analysis with transcript and comment extraction",
    docs_url="/"
)

# YouTube Scheduler configuration
YOUTUBE_SCHEDULER_CONFIG = {
    'channels': [
        '@WION',
        '@HT-Videos',
        '@ThePioneer.',
        '@CNN',
        '@indianexpress',
        '@TheHinduOfficial',
        '@themillenniumpost',
        '@Firstpost',
        '@TheQuint',
        '@businessstandard',
        '@timesofindia',
        '@TheTribunechd',
        '@indiadotcom',
        '@TheStatesman',
        '@TheEconomicTimes',
        '@thetelegraphindiaonline',
        '@NDTV',
        '@indiatoday',
        '@WashingtonPost',
        '@nytimes'
    ],
    'max_results_per_channel': 10,  # Reduced to avoid rate limiting
    'keywords': ['bangladesh', 'Jamaat', 'Save Hindus', 'Terrorists', 'Facist Yunus', 'Terrorist Yunus', 'Minority', 'Hindu nationalist', 'Hindu minority Bangladesh'],
    'hashtags': [],
    'include_comments': True,
    'include_transcripts': True,
    'comments_limit': 20,
    'interval_minutes': 1440,  # Run every 24 hours (safer for yt-dlp)
    'max_instances': 1,
    'coalesce': True,
    'misfire_grace_time': 300,  # 5 minutes graceS
    'enabled': True,  # Enabled by default for YouTube monitoring
    'days_back': 1,  # Only fetch videos from last 10 days for monitoring
    'use_date_range': False,  # Enable date range filtering
    # Duration filtering to skip too short/long videos
    'min_duration_seconds': 15,    # Skip videos shorter than 15 seconds
    'max_duration_seconds': 7200,  # Skip videos longer than 2 hours
    'filter_by_duration': True     # Enable duration filtering
}

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class YouTubeScrapeRequest(BaseModel):
    channels: List[str] = Field(..., description="List of YouTube channel handles (e.g., '@WION')")
    max_results: int = Field(100, ge=1, le=500, description="Maximum videos per channel (1-500)")
    published_after: Optional[str] = Field(None, description="Filter videos after this date (ISO format)")
    published_before: Optional[str] = Field(None, description="Filter videos before this date (ISO format)")
    keywords: Optional[List[str]] = Field(None, description="Keywords to filter videos")
    hashtags: Optional[List[str]] = Field(None, description="Hashtags to filter videos")
    include_comments: bool = Field(True, description="Whether to fetch comments")
    include_transcripts: bool = Field(True, description="Whether to fetch transcripts")
    comments_limit: int = Field(50, ge=1, le=100, description="Maximum comments per video")
    # Duration filtering parameters
    filter_by_duration: bool = Field(True, description="Whether to apply duration filtering")
    min_duration_seconds: int = Field(15, ge=1, le=3600, description="Minimum video duration in seconds (1-3600)")
    max_duration_seconds: int = Field(7200, ge=60, le=28800, description="Maximum video duration in seconds (60-28800)")

class YouTubeSchedulerConfigRequest(BaseModel):
    channels: List[str] = Field(..., description="YouTube channel handles to monitor")
    max_results_per_channel: int = Field(50, ge=1, le=200, description="Max videos per channel")
    keywords: Optional[List[str]] = Field(None, description="Keywords to filter videos")
    hashtags: Optional[List[str]] = Field(None, description="Hashtags to filter videos")
    include_comments: bool = Field(True, description="Whether to fetch comments")
    include_transcripts: bool = Field(True, description="Whether to fetch transcripts")
    comments_limit: int = Field(50, ge=1, le=100, description="Max comments per video")
    interval_minutes: int = Field(60, ge=30, le=1440, description="Interval in minutes (30-1440)")
    enabled: bool = Field(True, description="Whether YouTube monitoring is enabled")
    days_back: int = Field(3, ge=1, le=30, description="Only fetch videos from last N days (1-30)")
    use_date_range: bool = Field(True, description="Whether to use date range filtering")
    # Duration filtering parameters
    filter_by_duration: bool = Field(True, description="Whether to apply duration filtering")
    min_duration_seconds: int = Field(15, ge=1, le=3600, description="Minimum video duration in seconds (1-3600)")
    max_duration_seconds: int = Field(7200, ge=60, le=28800, description="Maximum video duration in seconds (60-28800)")

class YouTubeVideoModel(BaseModel):
    video_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    channel_title: Optional[str] = None
    channel_id: Optional[str] = None
    channel_handle: Optional[str] = None
    published_at: Optional[str] = None
    thumbnail: Optional[str] = None
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    duration: Optional[str] = None
    duration_seconds: Optional[int] = None
    tags: List[str] = []
    video_language: Optional[str] = None
    comments: List[str] = []
    english_transcript: Optional[str] = None
    bengali_transcript: Optional[str] = None
    transcript_languages: List[str] = []
    url: Optional[str] = None

    @classmethod
    def from_youtube_video(cls, video: YouTubeVideo):
        return cls(
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
            tags=video.tags or [],
            video_language=video.video_language,
            comments=video.comments or [],
            english_transcript=video.english_transcript,
            bengali_transcript=video.bengali_transcript,
            transcript_languages=video.transcript_languages or [],
            url=video.url
        )

# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

async def call_youtube_batch_classification_api(youtube_content_ids: List[str]) -> Dict[str, Any]:
    """Call the YouTube batch classification API to classify videos by their UUIDs"""
    if not youtube_content_ids:
        return {
            "successful": 0,
            "failed": 0,
            "total_classified": 0
        }
    
    try:
        async with aiohttp.ClientSession() as session:
            url = YOUTUBE_CLASSIFICATION_API_URL
            payload = {"youtube_content_ids": youtube_content_ids}
            
            logger.info(f"🤖 Calling YouTube classification API for {len(youtube_content_ids)} videos...")
            
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=YOUTUBE_CLASSIFICATION_API_TIMEOUT/1000)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # Response format: {"results": [...], "total_classified": N}
                    total_classified = result.get('total_classified', 0)
                    total_requested = len(youtube_content_ids)
                    failed_count = total_requested - total_classified
                    
                    logger.info(f"✅ YouTube Classification API: {total_classified} classified out of {total_requested} requested")
                    
                    return {
                        "successful": total_classified,
                        "failed": failed_count,
                        "total_classified": total_classified
                    }
                elif response.status == 404:
                    # All items were skipped - not an error, just no content to classify
                    error_text = await response.text()
                    logger.warning(f"⚠️ All YouTube videos were skipped for classification: {error_text}")
                    return {
                        "successful": 0,
                        "failed": 0,  # Not really "failed" - they were skipped
                        "total_classified": 0,
                        "skipped": len(youtube_content_ids)
                    }
                elif response.status == 400:
                    # Bad request (shouldn't happen with our validation, but handle it)
                    error_text = await response.text()
                    logger.error(f"❌ Bad request to YouTube classification API: {error_text}")
                    return {
                        "successful": 0,
                        "failed": len(youtube_content_ids),
                        "total_classified": 0
                    }
                else:
                    # Other HTTP errors
                    error_text = await response.text()
                    logger.error(f"❌ YouTube Classification API error: {response.status} - {error_text}")
                    return {
                        "successful": 0,
                        "failed": len(youtube_content_ids),
                        "total_classified": 0
                    }
                    
    except asyncio.TimeoutError:
        logger.error(f"⏰ YouTube Classification API timeout after {YOUTUBE_CLASSIFICATION_API_TIMEOUT/1000}s")
        return {
            "successful": 0,
            "failed": len(youtube_content_ids),
            "total_classified": 0
        }
    except Exception as e:
        logger.error(f"❌ YouTube Classification API exception: {e}")
        return {
            "successful": 0,
            "failed": len(youtube_content_ids),
            "total_classified": 0
        }

async def scrape_and_store_youtube_channel(channel_handle: str, api_key: str, **kwargs) -> Dict[str, Any]:
    """
    Scrape a single YouTube channel and store videos immediately
    
    Args:
        channel_handle (str): YouTube channel handle like '@WION'
        api_key (str): YouTube Data API key
        **kwargs: Additional scraping parameters
        
    Returns:
        Dict[str, Any]: Scraping and storage results with statistics
    """
    try:
        logger.info(f"🎥 Starting YouTube scrape for channel: {channel_handle}")
        
        # Initialize scraper
        scraper = YouTubeChannelScraper(api_key)
        
        # Get channel ID first
        channel_id = scraper.get_channel_id_from_handle(channel_handle)
        if not channel_id:
            logger.warning(f"Could not find channel ID for {channel_handle}")
            return {
                "channel": channel_handle,
                "scraped": 0,
                "stored": 0,
                "quota_used": scraper.get_quota_usage(),
                "status": "error",
                "error": "Channel ID not found"
            }
        
        # Get basic video list first (without full processing)
        videos = scraper._search_videos(
            channel_id=channel_id,
            max_results=kwargs.get('max_results', 100),
            published_after=kwargs.get('published_after'),
            published_before=kwargs.get('published_before'),
            keywords=kwargs.get('keywords'),
            hashtags=kwargs.get('hashtags')
        )
        
        if not videos:
            logger.info(f"✅ No videos found for {channel_handle}")
            return {
                "channel": channel_handle,
                "scraped": 0,
                "stored": 0,
                "quota_used": scraper.get_quota_usage(),
                "status": "success"
            }
        
        logger.info(f"📋 Found {len(videos)} videos from {channel_handle}, processing individually...")
        
        # Process and store each video individually
        stored_count = 0
        failed_count = 0
        stored_content_ids = []  # Collect UUIDs for batch classification
        
        for i, video in enumerate(videos):
            try:
                logger.info(f"[{i+1}/{len(videos)}] Processing video: {video.video_id}")
                
                # Add channel info
                channel_info = scraper._get_channel_info(channel_id)
                if channel_info:
                    video.channel_title = channel_info.get('snippet', {}).get('title', video.channel_title)
                    video.channel_handle = channel_handle
                
                # Get detailed statistics
                video_stats = scraper._get_videos_statistics([video.video_id])
                if video.video_id in video_stats:
                    stats = video_stats[video.video_id]
                    video.view_count = int(stats.get('viewCount', 0))
                    video.like_count = int(stats.get('likeCount', 0))
                    video.comment_count = int(stats.get('commentCount', 0))
                    video.duration = stats.get('duration')
                    video.duration_seconds = scraper.parse_duration(stats.get('duration'))
                    video.tags = stats.get('tags', [])
                    video.video_language = stats.get('defaultAudioLanguage', 'unknown')
                    video.raw_data.update({'statistics': stats})
                
                # Check duration filtering before processing transcripts/comments
                filter_by_duration = kwargs.get('filter_by_duration', True)
                min_duration_seconds = kwargs.get('min_duration_seconds', 15)
                max_duration_seconds = kwargs.get('max_duration_seconds', 7200)
                
                if filter_by_duration and video.duration_seconds is not None:
                    if min_duration_seconds and video.duration_seconds < min_duration_seconds:
                        logger.warning(f"Skipping video {video.video_id} - Too short ({video.duration_seconds}s < {min_duration_seconds}s)")
                        failed_count += 1
                        continue
                    if max_duration_seconds and video.duration_seconds > max_duration_seconds:
                        logger.warning(f"Skipping video {video.video_id} - Too long ({video.duration_seconds}s > {max_duration_seconds}s)")
                        failed_count += 1
                        continue
                    logger.info(f"Duration check passed: {video.duration_seconds}s")
                elif filter_by_duration and video.duration_seconds is None:
                    logger.warning(f"Skipping video {video.video_id} - Duration unknown")
                    failed_count += 1
                    continue
                
                # Get comments if requested
                if kwargs.get('include_comments', True):
                    try:
                        comments = scraper._get_video_comments(video.video_id, kwargs.get('comments_limit', 50))
                        video.comments = comments
                    except Exception as e:
                        logger.warning(f"Could not get comments for {video.video_id}: {e}")
                        video.comments = []
                
                # Get transcripts if requested
                if kwargs.get('include_transcripts', True):
                    try:
                        transcript_results = scraper._get_youtube_captions_exact(video.video_id)
                        if transcript_results:
                            video.transcript_languages = []
                            video.bengali_transcript = ""
                            video.english_transcript = ""
                            
                            for result in transcript_results:
                                lang = result['language']
                                transcript_text = ' '.join(item['text'] for item in result['transcript'])
                                video.transcript_languages.append(lang)
                                
                                if lang.startswith('bn'):
                                    video.bengali_transcript = transcript_text
                                elif lang.startswith('en'):
                                    video.english_transcript = transcript_text
                            
                            # Check if English transcript is available (requirement: must have English transcript)
                            if not video.english_transcript or not video.english_transcript.strip():
                                logger.warning(f"Skipping video {video.video_id} - No English transcript available")
                                failed_count += 1
                                continue  # Skip this video entirely
                        else:
                            logger.warning(f"Skipping video {video.video_id} - No transcripts found")
                            failed_count += 1
                            continue  # Skip this video entirely
                    except Exception as e:
                        logger.warning(f"Skipping video {video.video_id} - Could not get transcripts: {e}")
                        failed_count += 1
                        continue  # Skip this video entirely
                else:
                    # If transcripts not requested, skip the video (since we require English transcripts)
                    logger.warning(f"Skipping video {video.video_id} - Transcripts not requested but required")
                    failed_count += 1
                    continue
                
                # Final safety check before database insertion
                if not video.english_transcript or not video.english_transcript.strip():
                    logger.warning(f"Final check failed - Skipping video {video.video_id}: No English transcript")
                    failed_count += 1
                    continue
                
                # Store video immediately in database
                db_result = youtube_db_service.insert_single_video(video)
                if db_result['status'] == 'success':
                    stored_count += 1
                    stored_content_ids.append(db_result['content_id'])  # Collect UUID for classification
                    logger.info(f"💾 Stored video: {video.title[:50]}...")
                elif db_result['status'] == 'skipped':
                    logger.info(f"📋 Skipped existing video: {video.video_id}")
                    # Note: We don't count skipped videos as failed anymore
                else:
                    logger.warning(f"Failed to store video {video.video_id}: {db_result.get('error', 'Unknown error')}")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"❌ Error processing video {video.video_id}: {e}")
                failed_count += 1
                continue
        
        logger.info(f"✅ Channel {channel_handle}: {stored_count} stored, {failed_count} failed")
        
        # Call batch classification API for newly stored videos
        classification_result = {"successful": 0, "failed": 0, "total_classified": 0}
        if stored_content_ids:
            try:
                logger.info(f"🤖 Starting batch classification for {len(stored_content_ids)} new videos...")
                classification_result = await call_youtube_batch_classification_api(stored_content_ids)
                
                # Enhanced logging based on classification results
                total_classified = classification_result.get('total_classified', 0)
                skipped = classification_result.get('skipped', 0)
                failed = classification_result.get('failed', 0)
                
                if total_classified > 0:
                    logger.info(f"✅ Classification completed: {total_classified} videos classified")
                if skipped > 0:
                    logger.info(f"⚠️ Classification skipped: {skipped} videos were not eligible")
                if failed > 0:
                    logger.warning(f"❌ Classification failed: {failed} videos could not be processed")
                    
            except Exception as e:
                logger.error(f"❌ Batch classification failed: {e}")
        else:
            logger.info("📋 No new videos to classify")
        
        return {
            "channel": channel_handle,
            "scraped": len(videos),
            "stored": stored_count,
            "failed": failed_count,
            "quota_used": scraper.get_quota_usage(),
            "classification": classification_result,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"❌ Error scraping YouTube channel {channel_handle}: {e}")
        return {
            "channel": channel_handle,
            "error": str(e),
            "scraped": 0,
            "stored": 0,
            "failed": 0,
            "quota_used": 0,
            "status": "error"
        }

async def scrape_and_store_youtube_channels(channels: List[str], api_key: str, **kwargs) -> Dict[str, Any]:
    """
    Scrape multiple YouTube channels and store in database
    
    Args:
        channels (List[str]): List of channel handles
        api_key (str): YouTube Data API key
        **kwargs: Additional scraping parameters
        
    Returns:
        Dict[str, Any]: Complete operation results
    """
    try:
        logger.info(f"🚀 Starting YouTube scrape and store for {len(channels)} channels")
        
        all_videos = []
        results = []
        total_quota_used = 0
        
        # Process each channel with immediate storage
        total_stored = 0
        total_failed = 0
        total_scraped = 0
        total_classified = 0
        
        for channel in channels:
            result = await scrape_and_store_youtube_channel(channel, api_key, **kwargs)
            results.append(result)
            
            if result['status'] == 'success':
                total_stored += result.get('stored', 0)
                total_failed += result.get('failed', 0)
                total_scraped += result['scraped']
                total_quota_used += result['quota_used']
                total_classified += result.get('classification', {}).get('total_classified', 0)
        
        # Calculate summary statistics
        successful_channels = sum(1 for r in results if r['status'] == 'success')
        failed_channels = len(channels) - successful_channels
        
        return {
            "summary": {
                "channels_processed": len(channels),
                "successful_channels": successful_channels,
                "failed_channels": failed_channels,
                "total_scraped": total_scraped,
                "total_stored": total_stored,
                "total_failed": total_failed,
                "total_classified": total_classified,
                "quota_used": total_quota_used
            },
            "channel_results": results,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error in YouTube scrape and store operation: {e}")
        raise HTTPException(status_code=500, detail=f"YouTube operation failed: {str(e)}")

async def scheduled_youtube_job():
    """Scheduled YouTube monitoring job"""
    if not YOUTUBE_SCHEDULER_CONFIG.get('enabled', False):
        logger.info("📺 YouTube scheduled monitoring is disabled")
        return
    
    logger.info(f"📺 Starting scheduled YouTube monitoring at {datetime.datetime.now()}")
    logger.info(f"📺 Monitoring channels: {YOUTUBE_SCHEDULER_CONFIG['channels']}")
    
    # Get YouTube API key
    api_key = os.getenv('YOUTUBE_API_KEY')
    if not api_key:
        logger.error("❌ YouTube API key not configured for scheduled monitoring")
        return
    
    try:
        channels = YOUTUBE_SCHEDULER_CONFIG['channels']
        logger.info(f"📺 Monitoring {len(channels)} YouTube channels")
        
        # Calculate date range for filtering (only recent videos)
        published_after = None
        published_before = None
        if YOUTUBE_SCHEDULER_CONFIG.get('use_date_range', True):
            days_back = YOUTUBE_SCHEDULER_CONFIG.get('days_back', 3)
            end_date = datetime.datetime.now()
            start_date = end_date - datetime.timedelta(days=days_back)
            
            published_after = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            published_before = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            logger.info(f"📅 Filtering videos from last {days_back} days: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        # Execute YouTube scraping and storage
        result = await scrape_and_store_youtube_channels(
            channels=channels,
            api_key=api_key,
            max_results=YOUTUBE_SCHEDULER_CONFIG['max_results_per_channel'],
            published_after=published_after,
            published_before=published_before,
            keywords=YOUTUBE_SCHEDULER_CONFIG.get('keywords'),
            hashtags=YOUTUBE_SCHEDULER_CONFIG.get('hashtags'),
            include_comments=YOUTUBE_SCHEDULER_CONFIG['include_comments'],
            include_transcripts=YOUTUBE_SCHEDULER_CONFIG['include_transcripts'],
            comments_limit=YOUTUBE_SCHEDULER_CONFIG['comments_limit'],
            # Duration filtering parameters
            filter_by_duration=YOUTUBE_SCHEDULER_CONFIG.get('filter_by_duration', True),
            min_duration_seconds=YOUTUBE_SCHEDULER_CONFIG.get('min_duration_seconds', 15),
            max_duration_seconds=YOUTUBE_SCHEDULER_CONFIG.get('max_duration_seconds', 7200)
        )
        
        summary = result['summary']
        logger.info(f"✅ YouTube monitoring completed:")
        logger.info(f"   📺 Channels: {summary['successful_channels']}/{summary['channels_processed']} successful")
        logger.info(f"   🎥 Videos: {summary['total_scraped']} scraped, {summary['total_stored']} stored, {summary['total_failed']} failed")
        logger.info(f"   🔄 Quota used: {summary['quota_used']}")
        
    except Exception as e:
        logger.error(f"❌ Scheduled YouTube monitoring failed: {e}")

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "scheduler_running": scheduler.running,
        "service": "YouTube Content Monitoring"
    }

@app.post("/scrape-channels")
async def youtube_scrape_channels(req: YouTubeScrapeRequest):
    """
    Scrape YouTube channels and store videos in database
    
    This endpoint extracts videos from specified YouTube channels, including:
    - Video metadata (title, description, views, likes, etc.)
    - Comments (configurable limit)
    - Transcripts in multiple languages (English, Bengali)
    - Full storage in database with deduplication
    """
    # Get YouTube API key from environment
    api_key = os.getenv('YOUTUBE_API_KEY')
    if not api_key:
        raise HTTPException(
            status_code=500, 
            detail="YouTube API key not configured. Please set YOUTUBE_API_KEY environment variable."
        )
    
    try:
        # Execute scraping and storage operation
        result = await scrape_and_store_youtube_channels(
            channels=req.channels,
            api_key=api_key,
            max_results=req.max_results,
            published_after=req.published_after,
            published_before=req.published_before,
            keywords=req.keywords,
            hashtags=req.hashtags,
            include_comments=req.include_comments,
            include_transcripts=req.include_transcripts,
            comments_limit=req.comments_limit,
            # Duration filtering parameters
            filter_by_duration=req.filter_by_duration,
            min_duration_seconds=req.min_duration_seconds,
            max_duration_seconds=req.max_duration_seconds
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ YouTube scraping failed: {e}")
        raise HTTPException(status_code=500, detail=f"YouTube scraping failed: {str(e)}")

@app.get("/videos")
async def get_youtube_content(
    channel_handle: Optional[str] = None,
    search_term: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """
    Retrieve YouTube videos from database with optional filtering
    
    Args:
        channel_handle: Filter by specific channel (e.g., '@WION')
        search_term: Full-text search in title, description, transcript
        limit: Maximum number of videos to return
        offset: Number of videos to skip (for pagination)
    """
    try:
        if search_term:
            videos = youtube_db_service.search_videos(search_term, limit)
        elif channel_handle:
            videos = youtube_db_service.get_videos_by_channel(channel_handle, limit, offset)
        else:
            # Get recent videos if no filter specified
            videos = youtube_db_service.get_videos_for_analysis(limit)
        
        return {
            "videos": videos,
            "count": len(videos),
            "parameters": {
                "channel_handle": channel_handle,
                "search_term": search_term,
                "limit": limit,
                "offset": offset
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error retrieving YouTube videos: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve videos: {str(e)}")

@app.get("/stats")
async def get_youtube_stats():
    """Get YouTube database statistics and analytics"""
    try:
        stats = youtube_db_service.get_database_stats()
        return {
            "youtube_statistics": stats,
            "timestamp": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Error getting YouTube stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")

@app.get("/channels")
async def get_monitored_channels():
    """Get list of channels that have videos in the database"""
    try:
        conn = youtube_db_service.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                channel_handle,
                channel_title,
                COUNT(*) as video_count,
                MAX(published_at) as latest_video,
                AVG(view_count) as avg_views
            FROM youtube_content 
            WHERE channel_handle IS NOT NULL
            GROUP BY channel_handle, channel_title
            ORDER BY video_count DESC
        """)
        
        channels = []
        for row in cursor.fetchall():
            channels.append({
                "handle": row[0],
                "title": row[1],
                "video_count": row[2],
                "latest_video": row[3].isoformat() if row[3] else None,
                "avg_views": int(row[4]) if row[4] else 0
            })
        
        return {
            "channels": channels,
            "total_channels": len(channels)
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting channels: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get channels: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ---------------------------------------------------------------------------
# Scheduler Endpoints
# ---------------------------------------------------------------------------

@app.post("/schedule/configure")
async def configure_youtube_scheduler(req: YouTubeSchedulerConfigRequest):
    """Configure YouTube scheduled monitoring"""
    global YOUTUBE_SCHEDULER_CONFIG
    
    try:
        # Update configuration
        YOUTUBE_SCHEDULER_CONFIG.update({
            'channels': req.channels,
            'max_results_per_channel': req.max_results_per_channel,
            'keywords': req.keywords,
            'hashtags': req.hashtags,
            'include_comments': req.include_comments,
            'include_transcripts': req.include_transcripts,
            'comments_limit': req.comments_limit,
            'interval_minutes': req.interval_minutes,
            'enabled': req.enabled,
            'days_back': req.days_back,
            'use_date_range': req.use_date_range,
            # Duration filtering parameters
            'filter_by_duration': req.filter_by_duration,
            'min_duration_seconds': req.min_duration_seconds,
            'max_duration_seconds': req.max_duration_seconds
        })
        
        # Remove existing YouTube job
        try:
            scheduler.remove_job('youtube_monitoring_job')
        except:
            pass
        
        # Add new job if enabled
        if req.enabled:
            scheduler.add_job(
                scheduled_youtube_job,
                IntervalTrigger(minutes=req.interval_minutes),
                id='youtube_monitoring_job',
                name='YouTube Channel Monitoring',
                max_instances=1,
                coalesce=True,
                misfire_grace_time=YOUTUBE_SCHEDULER_CONFIG.get('misfire_grace_time', 300)
            )
            
            logger.info(f"📺 YouTube monitoring configured: {len(req.channels)} channels every {req.interval_minutes} minutes")
        else:
            logger.info("📺 YouTube monitoring disabled")
        
        return {
            "message": "YouTube scheduler configured successfully",
            "configuration": YOUTUBE_SCHEDULER_CONFIG,
            "status": "enabled" if req.enabled else "disabled"
        }
        
    except Exception as e:
        logger.error(f"❌ Error configuring YouTube scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to configure scheduler: {str(e)}")

@app.get("/schedule/status")
async def get_youtube_scheduler_status():
    """Get YouTube scheduler status and configuration"""
    try:
        youtube_jobs = []
        for job in scheduler.get_jobs():
            if job.id == 'youtube_monitoring_job':
                youtube_jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "enabled": True
                })
        
        return {
            "scheduler_running": scheduler.running,
            "youtube_monitoring": {
                "enabled": YOUTUBE_SCHEDULER_CONFIG.get('enabled', False),
                "configuration": YOUTUBE_SCHEDULER_CONFIG,
                "active_jobs": youtube_jobs
            },
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting YouTube scheduler status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")

@app.post("/schedule/trigger")
async def trigger_youtube_monitoring():
    """Manually trigger YouTube monitoring job"""
    try:
        api_key = os.getenv('YOUTUBE_API_KEY')
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="YouTube API key not configured. Please set YOUTUBE_API_KEY environment variable."
            )
        
        logger.info("🎬 Manually triggering YouTube monitoring...")
        await scheduled_youtube_job()
        
        return {
            "message": "YouTube monitoring triggered successfully",
            "timestamp": datetime.datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error triggering YouTube monitoring: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger monitoring: {str(e)}")

@app.post("/schedule/start")
async def start_scheduler():
    """Start the YouTube scheduler"""
    try:
        if not scheduler.running:
            scheduler.start()
            logger.info("🟢 YouTube scheduler started")
            return {"message": "YouTube scheduler started successfully", "status": "running"}
        else:
            return {"message": "YouTube scheduler is already running", "status": "running"}
    except Exception as e:
        logger.error(f"❌ Error starting scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {str(e)}")

@app.post("/schedule/stop")
async def stop_scheduler():
    """Stop the YouTube scheduler"""
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("🔴 YouTube scheduler stopped")
            return {"message": "YouTube scheduler stopped successfully", "status": "stopped"}
        else:
            return {"message": "YouTube scheduler is already stopped", "status": "stopped"}
    except Exception as e:
        logger.error(f"❌ Error stopping scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {str(e)}")

# ---------------------------------------------------------------------------
# Startup/Shutdown Events
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    """Initialize scheduler on startup"""
    # Add YouTube monitoring job if enabled
    if YOUTUBE_SCHEDULER_CONFIG.get('enabled', False):
        start_time = datetime.datetime.now() + datetime.timedelta(seconds=5)
        
        scheduler.add_job(
            scheduled_youtube_job,
            trigger=IntervalTrigger(
                minutes=YOUTUBE_SCHEDULER_CONFIG['interval_minutes'],
                start_date=start_time,
                jitter=10
            ),
            id='youtube_monitoring_job',
            name='YouTube Channel Monitoring',
            max_instances=YOUTUBE_SCHEDULER_CONFIG.get('max_instances', 1),
            coalesce=YOUTUBE_SCHEDULER_CONFIG.get('coalesce', True),
            misfire_grace_time=YOUTUBE_SCHEDULER_CONFIG.get('misfire_grace_time', 300),
            replace_existing=True
        )
        logger.info(f"📺 YouTube monitoring enabled - will start in 60 seconds at {start_time.strftime('%H:%M:%S')}")
        logger.info(f"🕐 Then every {YOUTUBE_SCHEDULER_CONFIG['interval_minutes']} minutes")
        logger.info(f"📺 Monitoring {len(YOUTUBE_SCHEDULER_CONFIG['channels'])} YouTube channels: {YOUTUBE_SCHEDULER_CONFIG['channels']}")
    else:
        logger.info(f"📺 YouTube monitoring is disabled")
    
    # Start scheduler
    scheduler.start()
    logger.info(f"🚀 YouTube Content Monitoring Server started")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    scheduler.shutdown()
    EXECUTOR.shutdown(wait=True)
    logger.info("🛑 YouTube server shutdown complete")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)