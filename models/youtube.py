"""
YouTube API Data Models

Pydantic models for YouTube scraping API requests and responses.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class YouTubeVideoModel(BaseModel):
    """YouTube video response model"""
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


class YouTubeScrapeRequest(BaseModel):
    """Request model for single YouTube channel scraping"""
    channel_handle: str = Field(..., description="YouTube channel handle (e.g., '@WION')")
    max_results: int = Field(100, ge=1, le=500, description="Maximum videos to fetch")
    published_after: Optional[str] = Field(None, description="Filter videos after this date (ISO format)")
    published_before: Optional[str] = Field(None, description="Filter videos before this date (ISO format)")
    keywords: Optional[List[str]] = Field(None, description="Keywords to filter videos")
    hashtags: Optional[List[str]] = Field(None, description="Hashtags to filter videos")
    include_comments: bool = Field(True, description="Whether to fetch comments")
    include_transcripts: bool = Field(True, description="Whether to fetch transcripts")
    comments_limit: int = Field(50, ge=1, le=100, description="Maximum comments per video")
    filter_by_duration: bool = Field(True, description="Whether to apply duration filtering")
    min_duration_seconds: int = Field(15, ge=1, le=3600, description="Minimum video duration")
    max_duration_seconds: int = Field(7200, ge=60, le=28800, description="Maximum video duration")


class YouTubeMultiScrapeRequest(BaseModel):
    """Request model for multiple YouTube channels scraping"""
    channels: List[str] = Field(..., description="List of YouTube channel handles")
    max_results: int = Field(50, ge=1, le=500, description="Maximum videos per channel")
    published_after: Optional[str] = Field(None, description="Filter videos after this date (ISO format)")
    published_before: Optional[str] = Field(None, description="Filter videos before this date (ISO format)")
    keywords: Optional[List[str]] = Field(None, description="Keywords to filter videos")
    hashtags: Optional[List[str]] = Field(None, description="Hashtags to filter videos")
    include_comments: bool = Field(True, description="Whether to fetch comments")
    include_transcripts: bool = Field(True, description="Whether to fetch transcripts")
    comments_limit: int = Field(50, ge=1, le=100, description="Maximum comments per video")
    filter_by_duration: bool = Field(True, description="Whether to apply duration filtering")
    min_duration_seconds: int = Field(15, ge=1, le=3600, description="Minimum video duration")
    max_duration_seconds: int = Field(7200, ge=60, le=28800, description="Maximum video duration")
    max_concurrent: int = Field(2, ge=1, le=5, description="Max concurrent channel operations")


class YouTubeSchedulerConfig(BaseModel):
    """YouTube scheduler configuration model"""
    channels: List[str] = Field(..., description="YouTube channel handles to monitor")
    max_results_per_channel: int = Field(50, ge=1, le=200, description="Max videos per channel")
    keywords: Optional[List[str]] = Field(None, description="Keywords to filter videos")
    hashtags: Optional[List[str]] = Field(None, description="Hashtags to filter videos")
    include_comments: bool = Field(True, description="Whether to fetch comments")
    include_transcripts: bool = Field(True, description="Whether to fetch transcripts")
    comments_limit: int = Field(50, ge=1, le=100, description="Max comments per video")
    interval_minutes: int = Field(60, ge=30, le=1440, description="Interval in minutes")
    enabled: bool = Field(True, description="Whether YouTube monitoring is enabled")
    days_back: int = Field(3, ge=1, le=30, description="Only fetch videos from last N days")
    use_date_range: bool = Field(True, description="Whether to use date range filtering")
    filter_by_duration: bool = Field(True, description="Whether to apply duration filtering")
    min_duration_seconds: int = Field(15, ge=1, le=3600, description="Minimum video duration")
    max_duration_seconds: int = Field(7200, ge=60, le=28800, description="Maximum video duration")
    # Additional scheduler-specific settings
    max_instances: int = Field(1, ge=1, le=3, description="Max concurrent job instances")
    coalesce: bool = Field(True, description="Combine missed runs")
    misfire_grace_time: int = Field(600, ge=60, le=3600, description="Grace time for delayed starts")


class YouTubeScrapeResponse(BaseModel):
    """Response model for YouTube scraping operations"""
    summary: Dict[str, Any] = Field(..., description="Summary statistics")
    channel_results: List[Dict[str, Any]] = Field(..., description="Detailed results per channel")
    timestamp: str = Field(..., description="Operation timestamp")


class YouTubeChannelStatus(BaseModel):
    """Status information for a YouTube channel"""
    available: bool
    circuit_breaker_state: str
    failure_count: int
    last_error: Optional[str] = None


class YouTubeVideoSearchRequest(BaseModel):
    """Request model for searching YouTube videos"""
    channel_handle: Optional[str] = Field(None, description="Filter by specific channel")
    search_term: Optional[str] = Field(None, description="Full-text search in title, description, transcript")
    limit: int = Field(100, ge=1, le=500, description="Maximum number of videos to return")
    offset: int = Field(0, ge=0, description="Number of videos to skip (for pagination)")


class YouTubeStatsResponse(BaseModel):
    """Response model for YouTube database statistics"""
    total_videos: int
    top_channels: List[Dict[str, Any]]
    recent_activity: List[Dict[str, Any]]
    language_distribution: List[Dict[str, Any]]