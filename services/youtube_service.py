"""
YouTube Scraping Service

Business logic for YouTube channel monitoring, transcript extraction,
and content analysis with comprehensive error handling.
"""

import asyncio
import os
from typing import List, Dict, Any, Optional
import aiohttp
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file before importing settings
load_dotenv()

from youtube_scrapers.channel_scraper import YouTubeChannelScraper
from youtube_scrapers.base import YouTubeVideo
from services.database_service import UnifiedDatabaseService
from services.youtube_api_pool import YouTubeAPIPool
from core.logging import get_scraper_logger, log_performance
from core.exceptions import (
    YouTubeScrapingError, APIError, ConfigurationError,
    retry_with_backoff, CircuitBreaker
)
from config.settings import get_settings

logger = get_scraper_logger("youtube_service")


class YouTubeService:
    """
    YouTube scraping service handling channel monitoring with advanced features
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.db_service = UnifiedDatabaseService()
        
        # Initialize API key pool for multi-key support
        api_keys = self.settings.youtube_api.get_api_keys()
        if not api_keys:
            logger.warning("No YouTube API keys configured. Some features may not work.")
            self.api_pool = None
            self.api_key = None  # For backward compatibility
        else:
            if len(api_keys) > 1:
                # Use pool for multiple keys
                self.api_pool = YouTubeAPIPool(
                    api_keys=api_keys,
                    quota_per_key=self.settings.youtube_api.quota_limit
                )
                self.api_key = None  # Not used when pool is active
                logger.info(f"[OK] Using API pool with {len(api_keys)} keys")
            else:
                # Single key mode (backward compatibility)
                self.api_pool = None
                self.api_key = api_keys[0]
                logger.info("[OK] Using single API key mode")
        
        # Circuit breakers for channels
        self.circuit_breakers = {}
        self.failure_counts = {}
    
    def _get_circuit_breaker(self, channel: str) -> CircuitBreaker:
        """Get or create circuit breaker for channel"""
        if channel not in self.circuit_breakers:
            self.circuit_breakers[channel] = CircuitBreaker(
                failure_threshold=5,  # Configurable
                recovery_timeout=600  # 10 minutes
            )
        return self.circuit_breakers[channel]
    
    async def scrape_channel(
        self,
        channel_handle: str,
        max_results: int = 50,
        published_after: Optional[str] = None,
        published_before: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        hashtags: Optional[List[str]] = None,
        include_comments: bool = True,
        include_transcripts: bool = True,
        comments_limit: int = 50,
        filter_by_duration: bool = True,
        min_duration_seconds: int = 15,
        max_duration_seconds: int = 1800
    ) -> List[YouTubeVideo]:
        """
        Scrape videos from a single YouTube channel
        
        Args:
            channel_handle: YouTube channel handle (e.g., '@WION')
            max_results: Maximum number of videos to fetch
            published_after: Filter videos after this date (ISO format)
            published_before: Filter videos before this date (ISO format)  
            keywords: Keywords to filter videos
            hashtags: Hashtags to filter videos
            include_comments: Whether to fetch comments
            include_transcripts: Whether to fetch transcripts
            comments_limit: Maximum comments per video
            filter_by_duration: Whether to apply duration filtering
            min_duration_seconds: Minimum video duration
            max_duration_seconds: Maximum video duration
            
        Returns:
            List of YouTubeVideo objects
            
        Raises:
            YouTubeScrapingError: When scraping fails
            ConfigurationError: When API key is missing
        """
        if not self.api_pool and not self.api_key:
            raise ConfigurationError("No YouTube API keys configured")
        
        if not channel_handle.startswith('@'):
            channel_handle = f'@{channel_handle}'
        
        try:
            with log_performance(logger, f"scraping YouTube channel {channel_handle}"):
                # Get API key from pool or use single key
                if self.api_pool:
                    # Estimate cost: channel lookup + search + video details
                    estimated_cost = 150  # Conservative estimate
                    api_key = self.api_pool.get_available_key(
                        estimated_cost=estimated_cost,
                        operation='search'
                    )
                    logger.debug(f"Using API key from pool for {channel_handle}")
                else:
                    api_key = self.api_key
                
                scraper = YouTubeChannelScraper(api_key)
                
                # Get channel ID first
                channel_id = scraper.get_channel_id_from_handle(channel_handle)
                if not channel_id:
                    raise YouTubeScrapingError(channel_handle, "Channel ID not found")
                
                # Search for videos
                videos = scraper._search_videos(
                    channel_id=channel_id,
                    max_results=max_results,
                    published_after=published_after,
                    published_before=published_before,
                    keywords=keywords,
                    hashtags=hashtags
                )
                
                if not videos:
                    logger.info(f"[OK] No videos found for {channel_handle}")
                    return []
                
                logger.info(f"[LIST] Found {len(videos)} videos from {channel_handle}, processing individually...")
                
                # Process each video with metadata, comments, and transcripts
                processed_videos = []
                skipped_count = 0
                skipped_reasons = {
                    'duration_too_short': 0,
                    'duration_too_long': 0,
                    'duration_unknown': 0,
                    'no_english_transcript': 0,
                    'no_transcripts': 0,
                    'transcript_error': 0
                }
                
                for i, video in enumerate(videos):
                    try:
                        logger.info(f"[{i+1}/{len(videos)}] Processing video: {video.video_id} (Channel: {channel_handle})")
                        
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
                        
                        # Apply duration filtering with detailed logging
                        if filter_by_duration and video.duration_seconds is not None:
                            if min_duration_seconds and video.duration_seconds < min_duration_seconds:
                                logger.warning(f"Skipping video {video.video_id} - Too short ({video.duration_seconds}s < {min_duration_seconds}s)")
                                skipped_count += 1
                                skipped_reasons['duration_too_short'] += 1
                                continue
                            if max_duration_seconds and video.duration_seconds > max_duration_seconds:
                                logger.warning(f"Skipping video {video.video_id} - Too long ({video.duration_seconds}s > {max_duration_seconds}s)")
                                skipped_count += 1
                                skipped_reasons['duration_too_long'] += 1
                                continue
                            logger.info(f"Duration check passed: {video.duration_seconds}s")
                        elif filter_by_duration and video.duration_seconds is None:
                            logger.warning(f"Skipping video {video.video_id} - Duration unknown")
                            skipped_count += 1
                            skipped_reasons['duration_unknown'] += 1
                            continue
                        
                        # Get comments if requested
                        if include_comments:
                            try:
                                comments = scraper._get_video_comments(video.video_id, comments_limit)
                                video.comments = comments
                                logger.info(f"Retrieved {len(comments)} comments for video {video.video_id}")
                            except Exception as e:
                                logger.warning(f"Could not get comments for {video.video_id}: {e}")
                                video.comments = []
                        
                        # Get transcripts if requested - this is critical for our use case
                        if include_transcripts:
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
                                    
                                    logger.info(f"Found transcripts in languages: {video.transcript_languages}")
                                    
                                    # Check if English transcript is available (requirement)
                                    if not video.english_transcript or not video.english_transcript.strip():
                                        logger.warning(f"Skipping video {video.video_id} - No English transcript available")
                                        skipped_count += 1
                                        skipped_reasons['no_english_transcript'] += 1
                                        continue
                                    else:
                                        logger.info(f"[OK] Video {video.video_id} has English transcript ({len(video.english_transcript)} chars)")
                                else:
                                    logger.warning(f"Skipping video {video.video_id} - No transcripts found")
                                    skipped_count += 1
                                    skipped_reasons['no_transcripts'] += 1
                                    continue
                            except Exception as e:
                                logger.warning(f"Skipping video {video.video_id} - Could not get transcripts: {e}")
                                skipped_count += 1
                                skipped_reasons['transcript_error'] += 1
                                continue
                        else:
                            # If transcripts not requested, skip video (requirement for our system)
                            logger.warning(f"Skipping video {video.video_id} - Transcripts not requested but required")
                            skipped_count += 1
                            skipped_reasons['no_transcripts'] += 1
                            continue
                        
                        # Final safety check
                        if not video.english_transcript or not video.english_transcript.strip():
                            logger.warning(f"Final check failed - Skipping video {video.video_id}: No English transcript")
                            skipped_count += 1
                            skipped_reasons['no_english_transcript'] += 1
                            continue
                        
                        processed_videos.append(video)
                        logger.info(f"[OK] Video {video.video_id} processed successfully with English transcript")
                        
                    except Exception as e:
                        logger.error(f"[ERROR] Error processing video {video.video_id}: {e}")
                        skipped_count += 1
                        continue
                
                # Log detailed processing summary with English transcript info
                eng_transcript_count = len([v for v in processed_videos if v.english_transcript and v.english_transcript.strip()])
                logger.info(f"[OK] Channel {channel_handle} processing completed:")
                logger.info(f"   [LIST] Total found: {len(videos)} videos")
                logger.info(f"   [OK] Successfully processed: {len(processed_videos)} videos")
                logger.info(f"   [TEXT] With English transcripts: {eng_transcript_count} videos")
                logger.info(f"   [WARN]  Skipped: {skipped_count} videos")
                
                if skipped_count > 0:
                    logger.info(f"   [LIST] Skip reasons breakdown:")
                    for reason, count in skipped_reasons.items():
                        if count > 0:
                            logger.info(f"      - {reason.replace('_', ' ').title()}: {count}")
                
                # Record API usage if using pool
                if self.api_pool and api_key:
                    # Actual cost calculation based on operations performed
                    actual_cost = 100  # Base search cost
                    actual_cost += len(videos) * 3  # Video details and stats
                    if include_comments:
                        actual_cost += len(processed_videos) * 1  # Comments
                    
                    self.api_pool.record_usage(api_key, actual_cost, success=True)
                    logger.debug(f"Recorded {actual_cost} units usage for API key")
                
                return processed_videos
                
        except Exception as e:
            logger.error(f"YouTube scraping failed for {channel_handle}: {e}")
            
            # Record failure if using pool
            if self.api_pool and 'api_key' in locals():
                self.api_pool.record_usage(api_key, 0, success=False, error=str(e))
            
            raise YouTubeScrapingError(channel_handle, str(e))
    
    async def scrape_and_store_channel(
        self,
        channel_handle: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape channel and immediately store videos in database
        
        Args:
            channel_handle: YouTube channel handle
            **kwargs: Additional scraping parameters
            
        Returns:
            Dictionary with scraping and storage statistics
        """
        try:
            # Check circuit breaker
            circuit_breaker = self._get_circuit_breaker(channel_handle)
            if circuit_breaker.state == 'OPEN':
                raise YouTubeScrapingError(
                    channel_handle,
                    f"Circuit breaker open (failed {circuit_breaker.failure_count} times)"
                )
            
            logger.info(f"[VIDEO] Starting YouTube scrape for channel: {channel_handle}")
            
            # Scrape videos
            videos = await self.scrape_channel(channel_handle, **kwargs)
            
            if not videos:
                return {
                    "channel": channel_handle,
                    "scraped": 0,
                    "stored": 0,
                    "failed": 0,
                    "quota_used": 0,
                    "classification": {"successful": 0, "failed": 0},
                    "status": "success"
                }
            
            # Store videos individually in database with detailed logging
            stored_count = 0
            failed_count = 0
            skipped_existing_count = 0
            stored_content_ids = []
            
            logger.info(f"[SAVE] Starting database storage for {len(videos)} processed videos...")
            
            for i, video in enumerate(videos):
                try:
                    logger.info(f"[{i+1}/{len(videos)}] Storing video: {video.video_id} (Channel: {channel_handle})")
                    db_result = self.db_service.insert_single_video(video)
                    
                    if db_result['status'] == 'success':
                        stored_count += 1
                        stored_content_ids.append(db_result['content_id'])
                        logger.info(f"[SAVE] Stored video: {video.title[:50]}... (UUID: {db_result['content_id']})")
                    elif db_result['status'] == 'skipped':
                        skipped_existing_count += 1
                        logger.info(f"[LIST] Skipped existing video: {video.video_id} (already in database)")
                        # Note: We don't count skipped videos as failed anymore
                    else:
                        failed_count += 1
                        logger.warning(f"[ERROR] Failed to store video {video.video_id}: {db_result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.error(f"[ERROR] Exception storing video {video.video_id}: {e}")
                    failed_count += 1
            
            # Log storage summary with detailed counts
            logger.info(f"[SAVE] Database storage completed for {channel_handle}:")
            logger.info(f"   📥 Videos sent to database: {len(videos)}")
            logger.info(f"   [OK] New videos stored: {stored_count}")
            logger.info(f"   [CYCLE] Already existed (duplicates): {skipped_existing_count}") 
            logger.info(f"   [ERROR] Failed to store: {failed_count}")
            
            # Call batch classification API with enhanced logging
            classification_result = {"successful": 0, "failed": 0, "total_classified": 0}
            logger.info(f"[SEARCH] DEBUG: stored_content_ids = {stored_content_ids}")
            logger.info(f"[SEARCH] DEBUG: stored_content_ids length = {len(stored_content_ids)}")
            if stored_content_ids:
                logger.info(f"[AI] Starting batch classification for {channel_handle}:")
                logger.info(f"   [SEND] Sending {len(stored_content_ids)} videos for classification...")
                classification_result = await self._classify_videos(stored_content_ids, channel_handle)
                logger.info(f"[SEARCH] DEBUG: classification_result = {classification_result}")
                
                # Enhanced logging based on classification results
                total_classified = classification_result.get('total_classified', 0)
                skipped = classification_result.get('skipped', 0) 
                failed = classification_result.get('failed', 0)
                
                logger.info(f"[AI] Classification results for {channel_handle}:")
                if total_classified > 0:
                    logger.info(f"   [OK] Successfully classified: {total_classified} videos")
                if skipped > 0:
                    logger.info(f"   [WARN] Skipped classification: {skipped} videos (not eligible)")
                if failed > 0:
                    logger.warning(f"   [ERROR] Failed classification: {failed} videos")
            else:
                logger.info(f"[LIST] No new videos to classify for {channel_handle} (all were duplicates or failed storage)")
            
            # Reset circuit breaker on success
            circuit_breaker.on_success()
            self.failure_counts[channel_handle] = 0
            
            logger.info(f"[OK] Channel {channel_handle} completed successfully:")
            logger.info(f"   [SEARCH] Videos found: {len(videos)}")
            logger.info(f"   [TEXT] With English transcripts: {len([v for v in videos if hasattr(v, 'english_transcript') and v.english_transcript and v.english_transcript.strip()])}")
            logger.info(f"   [SAVE] New videos stored: {stored_count}")
            logger.info(f"   [REFRESH] Duplicates skipped: {skipped_existing_count}")
            logger.info(f"   [ERROR] Failed storage: {failed_count}")
            logger.info(f"   [AI] Sent for classification: {len(stored_content_ids)}")
            logger.info(f"   [OK] Successfully classified: {classification_result.get('total_classified', 0)}")
            
            # Add quota usage tracking (could be enhanced to track actual API usage)
            quota_used = len(videos) * 2  # Rough estimate: 1 for search, 1 for details per video
            
            return {
                "channel": channel_handle,
                "scraped": len(videos),
                "stored": stored_count,
                "failed": failed_count,
                "skipped_existing": skipped_existing_count,
                "quota_used": quota_used,
                "classification": classification_result,
                "status": "success"
            }
            
        except YouTubeScrapingError as e:
            # Handle expected errors
            circuit_breaker = self._get_circuit_breaker(channel_handle)
            circuit_breaker.on_failure()
            self.failure_counts[channel_handle] = self.failure_counts.get(channel_handle, 0) + 1
            
            logger.error(f"YouTube scraping failed for {channel_handle}: {e.message}")
            return {
                "channel": channel_handle,
                "error": e.message,
                "scraped": 0,
                "stored": 0,
                "failed": 0,
                "quota_used": 0,
                "classification": {"successful": 0, "failed": 0},
                "status": "error"
            }
        except Exception as e:
            # Handle unexpected errors  
            circuit_breaker = self._get_circuit_breaker(channel_handle)
            circuit_breaker.on_failure()
            self.failure_counts[channel_handle] = self.failure_counts.get(channel_handle, 0) + 1
            
            logger.error(f"Unexpected error for {channel_handle}: {e}")
            return {
                "channel": channel_handle,
                "error": str(e),
                "scraped": 0,
                "stored": 0,
                "failed": 0,
                "quota_used": 0,
                "classification": {"successful": 0, "failed": 0},
                "status": "error"
            }
    
    def get_quota_status(self) -> Dict[str, Any]:
        """
        Get current quota status for all API keys.
        
        Returns:
            Dictionary with quota usage information
        """
        if self.api_pool:
            return self.api_pool.get_quota_summary()
        else:
            # Single key mode - return simple status
            return {
                "mode": "single_key",
                "keys": [{"index": 1, "status": "active" if self.api_key else "not_configured"}],
                "message": "Multi-key rotation not enabled"
            }
    
    async def scrape_multiple_channels(
        self,
        channels: List[str],
        max_concurrent: int = 2,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape multiple YouTube channels with concurrency control
        
        Args:
            channels: List of channel handles
            max_concurrent: Maximum concurrent operations
            **kwargs: Additional scraping parameters
            
        Returns:
            Dictionary with comprehensive results
        """
        logger.info(f"[START] Starting YouTube batch scraping for {len(channels)} channels")
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(channel):
            async with semaphore:
                return await self.scrape_and_store_channel(channel, **kwargs)
        
        # Execute all scraping operations
        results = await asyncio.gather(
            *[scrape_with_semaphore(channel) for channel in channels],
            return_exceptions=True
        )
        
        # Process results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Channel scraping failed for {channels[i]}: {result}")
                processed_results.append({
                    "channel": channels[i],
                    "error": str(result),
                    "scraped": 0,
                    "stored": 0,
                    "status": "error"
                })
            else:
                processed_results.append(result)
        
        # Calculate summary
        summary = self._calculate_batch_summary(processed_results)
        
        logger.info(f"[OK] YouTube batch scraping completed:")
        logger.info(f"   [TV] Channels processed: {summary['successful_channels']}/{summary['channels_processed']} successful")
        logger.info(f"   [VIDEO] Videos: {summary['total_scraped']} scraped, {summary['total_stored']} stored, {summary['total_failed']} failed")
        logger.info(f"   [AI] Classification: {summary['total_classified']} videos classified")
        logger.info(f"   [REFRESH] Quota used: {summary.get('quota_used', 0)}")
        
        # Log any failed channels
        failed_channels = [r for r in processed_results if r.get("status") == "error"]
        if failed_channels:
            logger.warning(f"[ERROR] Failed channels: {[r['channel'] for r in failed_channels]}")
        
        return {
            "summary": summary,
            "channel_results": processed_results,
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_videos_by_channel(
        self,
        channel_handle: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get stored videos for a specific channel"""
        try:
            with self.db_service.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT id, video_id, title, description, published_at, 
                               view_count, like_count, comment_count, duration,
                               channel_title, url, created_at
                        FROM youtube_content 
                        WHERE channel_handle = %s
                        ORDER BY published_at DESC
                        LIMIT %s OFFSET %s
                    """, (channel_handle, limit, offset))
                    
                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
                    
        except Exception as e:
            logger.error(f"Error retrieving videos for {channel_handle}: {e}")
            raise
    
    def get_monitored_channels(self) -> List[Dict[str, Any]]:
        """Get list of channels that have videos in database"""
        try:
            return self.db_service.get_youtube_database_stats().get('top_channels', [])
        except Exception as e:
            logger.error(f"Error getting monitored channels: {e}")
            return []
    
    def get_channel_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status information for all monitored channels"""
        status = {}
        
        # Get configured channels from settings
        configured_channels = self.settings.youtube_scheduler.channels
        
        for channel in configured_channels:
            circuit_breaker = self.circuit_breakers.get(channel)
            failure_count = self.failure_counts.get(channel, 0)
            
            status[channel] = {
                "available": True,
                "circuit_breaker_state": circuit_breaker.state if circuit_breaker else "CLOSED",
                "failure_count": failure_count,
                "last_error": None
            }
        
        return status
    
    def reset_channel_failures(self, channel: str = None):
        """Reset failure counts and circuit breakers for specific channel or all"""
        if channel:
            if channel in self.failure_counts:
                self.failure_counts[channel] = 0
            if channel in self.circuit_breakers:
                self.circuit_breakers[channel].on_success()
            logger.info(f"Reset failures for channel: {channel}")
        else:
            self.failure_counts.clear()
            for cb in self.circuit_breakers.values():
                cb.on_success()
            logger.info("Reset failures for all channels")
    
    # =============================================================================
    # Private Helper Methods
    # =============================================================================
    
    async def _classify_videos(self, content_ids: List[str], channel_handle: str) -> Dict[str, Any]:
        """
        Call YouTube classification API with comprehensive logging
        Handles batching with maximum 5 videos per API call
        
        Args:
            content_ids: List of video content IDs (UUIDs)
            channel_handle: YouTube channel handle for logging
            
        Returns:
            Dictionary with classification results
        """
        if not content_ids:
            return {"successful": 0, "failed": 0, "total_classified": 0}
        
        # Split into batches of 5
        batch_size = 5
        batches = [content_ids[i:i + batch_size] for i in range(0, len(content_ids), batch_size)]
        
        logger.info(f"[AI] Starting batch classification for {channel_handle}: {len(content_ids)} videos in {len(batches)} batches (max 5 per batch)")
        
        total_successful = 0
        total_failed = 0
        total_classified = 0
        total_skipped = 0
        
        for batch_num, batch_ids in enumerate(batches, 1):
            logger.info(f"[BATCH] Processing batch {batch_num}/{len(batches)} for {channel_handle} with {len(batch_ids)} videos...")
            
            batch_result = await self._classify_single_batch(batch_ids, batch_num, channel_handle)
            
            total_successful += batch_result.get('successful', 0)
            total_failed += batch_result.get('failed', 0)
            total_classified += batch_result.get('total_classified', 0)
            total_skipped += batch_result.get('skipped', 0)
        
        logger.info(f"[OK] Batch classification completed for {channel_handle}: {total_classified} classified, {total_failed} failed, {total_skipped} skipped")
        
        return {
            "successful": total_successful,
            "failed": total_failed,
            "total_classified": total_classified,
            "skipped": total_skipped
        }
    
    async def _classify_single_batch(self, content_ids: List[str], batch_num: int, channel_handle: str) -> Dict[str, Any]:
        """
        Classify a single batch of videos (max 5)
        
        Args:
            content_ids: List of video content IDs (UUIDs) for this batch
            batch_num: Batch number for logging
            channel_handle: YouTube channel handle for logging
            
        Returns:
            Dictionary with classification results for this batch
        """
        try:
            import time
            start_time = time.time()
            
            timeout = aiohttp.ClientTimeout(total=self.settings.classification_api.timeout_seconds)
            url = self.settings.classification_api.youtube_api_url
            payload = {"youtube_content_ids": content_ids}
            
            logger.info(f"[WEB] Batch {batch_num} for {channel_handle}: Calling API with {len(content_ids)} videos (URL: {url})")
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        # Response format: {"results": [...], "total_classified": N}
                        total_classified = result.get('total_classified', 0)
                        total_requested = len(content_ids)
                        failed_count = total_requested - total_classified
                        
                        elapsed_time = time.time() - start_time
                        logger.info(f"[OK] Batch {batch_num} for {channel_handle}: {total_classified} classified out of {total_requested} requested (took {elapsed_time:.1f}s)")
                        
                        return {
                            "successful": total_classified,
                            "failed": failed_count,
                            "total_classified": total_classified
                        }
                    elif response.status == 404:
                        # All items were skipped - not an error, just no content to classify
                        error_text = await response.text()
                        logger.warning(f"[WARN] Batch {batch_num} for {channel_handle}: All videos skipped for classification: {error_text}")
                        return {
                            "successful": 0,
                            "failed": 0,  # Not really "failed" - they were skipped
                            "total_classified": 0,
                            "skipped": len(content_ids)
                        }
                    elif response.status == 202:
                        # Accepted for async processing - this is a success!
                        result = await response.json()
                        logger.info(f"[OK] Batch {batch_num} for {channel_handle}: Accepted for async processing - {result.get('message', 'Processing in background')}")
                        
                        # For 202, we consider all items as successfully submitted
                        return {
                            "successful": len(content_ids),
                            "failed": 0,
                            "total_classified": len(content_ids)  # Marked as classified since they're processing
                        }
                    elif response.status == 400:
                        # Bad request (shouldn't happen with our validation, but handle it)
                        error_text = await response.text()
                        logger.error(f"[ERROR] Batch {batch_num} for {channel_handle}: Bad request to classification API: {error_text}")
                        return {
                            "successful": 0,
                            "failed": len(content_ids),
                            "total_classified": 0
                        }
                    else:
                        # Other HTTP errors (500, etc.)
                        error_text = await response.text()
                        logger.error(f"[ERROR] Batch {batch_num} for {channel_handle}: Classification API error {response.status}: {error_text}")
                        return {
                            "successful": 0,
                            "failed": len(content_ids),
                            "total_classified": 0
                        }
                        
        except asyncio.TimeoutError:
            elapsed_time = time.time() - start_time
            logger.error(f"[TIME] Batch {batch_num} for {channel_handle}: Classification API timeout after {elapsed_time:.1f}s (configured timeout: {self.settings.classification_api.timeout_seconds}s)")
            return {
                "successful": 0,
                "failed": len(content_ids),
                "total_classified": 0
            }
        except Exception as e:
            logger.error(f"[ERROR] Batch {batch_num} for {channel_handle}: Classification API exception: {e}")
            return {
                "successful": 0,
                "failed": len(content_ids),
                "total_classified": 0
            }
    
    def _calculate_batch_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate summary statistics for batch operation"""
        total_scraped = sum(r.get("scraped", 0) for r in results)
        total_stored = sum(r.get("stored", 0) for r in results)
        total_failed = sum(r.get("failed", 0) for r in results)
        total_skipped = sum(r.get("skipped_existing", 0) for r in results)
        total_classified = sum(r.get("classification", {}).get("total_classified", 0) for r in results)
        total_quota_used = sum(r.get("quota_used", 0) for r in results)
        successful_channels = len([r for r in results if r.get("status") == "success"])
        failed_channels = len(results) - successful_channels
        
        return {
            "channels_processed": len(results),
            "successful_channels": successful_channels,
            "failed_channels": failed_channels,
            "total_scraped": total_scraped,
            "total_stored": total_stored,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "total_classified": total_classified,
            "quota_used": total_quota_used
        }