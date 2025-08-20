"""
Scheduler API Data Models

Pydantic models for scheduler control and monitoring API.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from enum import Enum

from models.news import NewsSchedulerConfig
from models.youtube import YouTubeSchedulerConfig


class SchedulerAction(str, Enum):
    """Available scheduler actions"""
    START = "start"
    STOP = "stop"
    STATUS = "status"
    CONFIGURE_NEWS = "configure_news"
    CONFIGURE_YOUTUBE = "configure_youtube"
    TRIGGER_NEWS = "trigger_news"
    TRIGGER_YOUTUBE = "trigger_youtube"
    RESET_FAILURES = "reset_failures"


class SchedulerControlRequest(BaseModel):
    """Request model for scheduler control operations"""
    action: SchedulerAction = Field(..., description="Action to perform")
    news_config: Optional[NewsSchedulerConfig] = Field(None, description="News scheduler configuration")
    youtube_config: Optional[YouTubeSchedulerConfig] = Field(None, description="YouTube scheduler configuration")


class JobInfo(BaseModel):
    """Information about a scheduled job"""
    id: str
    name: str
    next_run_time: Optional[str] = None
    trigger: str
    max_instances: Optional[int] = None
    coalesce: Optional[bool] = None
    misfire_grace_time: Optional[int] = None


class JobStats(BaseModel):
    """Statistics for a scheduled job"""
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_duration: float = 0.0
    average_duration: float = 0.0
    last_run_time: Optional[str] = None
    last_error: Optional[str] = None
    last_summary: Optional[Dict[str, Any]] = None


class ServiceStatus(BaseModel):
    """Status information for scraping services"""
    news_outlets: Dict[str, Dict[str, Any]] = {}
    youtube_channels: Dict[str, Dict[str, Any]] = {}


class SchedulerConfiguration(BaseModel):
    """Complete scheduler configuration"""
    news: Dict[str, Any]
    youtube: Dict[str, Any]


class SchedulerStatusResponse(BaseModel):
    """Response model for scheduler status"""
    running: bool
    total_jobs: int
    job_details: List[JobInfo]
    configurations: SchedulerConfiguration
    job_stats: Dict[str, JobStats] = {}
    service_status: ServiceStatus
    timestamp: str = Field(..., description="Status timestamp")


class SchedulerControlResponse(BaseModel):
    """Response model for scheduler control operations"""
    action_performed: str
    message: str
    status: str  # "running" or "stopped"
    available_actions: List[str] = []
    job_details: List[JobInfo] = []
    timestamp: str = Field(..., description="Response timestamp")


class TriggerJobRequest(BaseModel):
    """Request model for triggering jobs manually"""
    job_type: str = Field(..., description="Type of job to trigger: 'news' or 'youtube'")


class JobTriggerResponse(BaseModel):
    """Response model for manual job triggering"""
    job_type: str
    status: str  # "success" or "error"
    message: str
    result: Optional[Dict[str, Any]] = None


class SchedulerConfigRequest(BaseModel):
    """Request model for scheduler configuration updates"""
    news_config: Optional[NewsSchedulerConfig] = None
    youtube_config: Optional[YouTubeSchedulerConfig] = None


# Re-export configs for convenience
NewsSchedulerConfig = NewsSchedulerConfig
YouTubeSchedulerConfig = YouTubeSchedulerConfig