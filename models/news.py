"""
News API Data Models

Pydantic models for news scraping API requests and responses.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime


class MediaItemModel(BaseModel):
    """Media item within an article"""
    url: str
    caption: Optional[str] = None
    type: Optional[str] = None  # "image", "video", etc.


class ArticleModel(BaseModel):
    """News article response model"""
    title: Optional[str] = None
    published_at: Optional[str] = None
    url: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    media: List[MediaItemModel] = []
    outlet: Optional[str] = None
    tags: List[str] = []
    section: Optional[str] = None


class NewsScrapeRequest(BaseModel):
    """Request model for news scraping"""
    outlet: str = Field(..., description="Target news outlet")
    keyword: str = Field("bangladesh", description="Search keyword")
    limit: int = Field(30, ge=1, le=500, description="Maximum articles (1-500)")
    page_size: int = Field(50, ge=1, le=100, description="Page size (1-100)")


class NewsMultiScrapeRequest(BaseModel):
    """Request model for multi-outlet news scraping"""
    outlets: List[str] = Field(..., description="List of outlets to scrape")
    keyword: str = Field("bangladesh", description="Search keyword")
    limit: int = Field(30, ge=1, le=500, description="Maximum articles per outlet")
    page_size: int = Field(50, ge=1, le=100, description="Page size")
    max_concurrent: int = Field(3, ge=1, le=10, description="Max concurrent operations")


class NewsSchedulerConfig(BaseModel):
    """News scheduler configuration model"""
    outlets: List[str] = Field(..., description="Outlets to scrape automatically")
    keyword: str = Field("bangladesh", description="Search keyword")
    limit: int = Field(50, ge=1, le=500, description="Articles per outlet")
    page_size: int = Field(25, ge=1, le=100, description="Page size")
    interval_minutes: int = Field(30, ge=5, le=1440, description="Interval in minutes")
    max_instances: int = Field(1, ge=1, le=5, description="Max concurrent job instances")
    coalesce: bool = Field(True, description="Combine missed runs")
    misfire_grace_time: int = Field(300, ge=60, le=3600, description="Grace time for delayed starts")
    jitter: int = Field(10, ge=0, le=60, description="Random jitter in seconds")
    max_retries_per_outlet: int = Field(2, ge=0, le=10, description="Max retries per outlet")
    timeout_per_outlet: int = Field(180, ge=30, le=600, description="Timeout per outlet in seconds")
    circuit_breaker_threshold: int = Field(5, ge=1, le=20, description="Circuit breaker threshold")


class NewsScrapeResponse(BaseModel):
    """Response model for news scraping operations"""
    summary: Dict[str, Any] = Field(..., description="Summary statistics")
    results: List[Dict[str, Any]] = Field(..., description="Detailed results per outlet")
    timestamp: str = Field(..., description="Operation timestamp")


class NewsOutletStatus(BaseModel):
    """Status information for a news outlet"""
    available: bool
    circuit_breaker_state: str
    failure_count: int
    last_error: Optional[str] = None