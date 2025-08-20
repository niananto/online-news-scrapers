"""
Unified Configuration Management for Scraping Service

This module provides centralized configuration using Pydantic Settings,
replacing scattered configuration across multiple files.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
import os


class DatabaseSettings(BaseSettings):
    """Database configuration settings"""
    host: str = Field(default="localhost", env="DB_HOST")
    database: str = Field(default="shottify_db_new", env="DB_DATABASE") 
    user: str = Field(default="postgres", env="DB_USER")
    password: str = Field(default="shottify123", env="DB_PASSWORD")
    port: int = Field(default=5432, env="DB_PORT")
    
    class Config:
        env_prefix = "DB_"
        env_file = ".env"
        extra = "ignore"


class NewsSchedulerSettings(BaseSettings):
    """News scraping scheduler configuration"""
    outlets: List[str] = Field(default=[
        'hindustan_times', 'business_standard', 'news18', 'firstpost',
        'republic_world', 'india_dotcom', 'statesman', 'daily_pioneer'
        # 'south_asia_monitor', 'economic_times', 'india_today', 'ndtv',
        # 'the_tribune', 'indian_express', 'millennium_post', 'times_of_india',
        # 'deccan_herald', 'abp_live', 'the_quint', 'the_guardian',
        # 'washington_post', 'wion', 'telegraph_india', 'the_hindu',
        # 'bbc', 'cnn', 'aljazeera', 'new_york_times', 'reuters', 'the_diplomat'
    ])
    keyword: str = Field(default="bangladesh", env="NEWS_KEYWORD")
    limit: int = Field(default=5, ge=1, le=500, env="NEWS_LIMIT")
    page_size: int = Field(default=25, ge=1, le=100, env="NEWS_PAGE_SIZE")
    interval_minutes: int = Field(default=30, ge=5, le=1440, env="NEWS_INTERVAL_MINUTES")
    
    # Enhanced scheduler options
    max_instances: int = Field(default=1, ge=1, le=5)
    coalesce: bool = Field(default=True)
    misfire_grace_time: int = Field(default=60, ge=60, le=3600)
    jitter: int = Field(default=10, ge=0, le=60)
    max_retries_per_outlet: int = Field(default=2, ge=0, le=10)
    timeout_per_outlet: int = Field(default=180, ge=30, le=600)
    circuit_breaker_threshold: int = Field(default=5, ge=1, le=20)
    
    class Config:
        env_prefix = "NEWS_"
        env_file = ".env"
        extra = "ignore"


class YouTubeSchedulerSettings(BaseSettings):
    """YouTube scraping scheduler configuration"""
    channels: List[str] = Field(default=[
        '@Firstpost', '@CNN', '@BBCNews' , '@WION', '@TheStatesman' , 
        '@HT-Videos', '@TheHinduOfficial', '@RepublicWorld' , '@nytimes' , '@theGuardian' , 
        '@TheQuint', '@timesofindia', '@indiadotcom', '@NDTV' , '@Thediplomatmagazine'
    ])
    max_results_per_channel: int = Field(default=10, ge=1, le=200, env="YT_MAX_RESULTS")
    keywords: Optional[List[str]] = Field(default=[
        'bangladesh', 'Younus', 'Sheikh Hasina', 'Facist Younus', 'SaveSecularBangladesh', 'StopHinduPersecution'
    ])
    hashtags: Optional[List[str]] = Field(default=[])
    include_comments: bool = Field(default=True)
    include_transcripts: bool = Field(default=True)
    comments_limit: int = Field(default=20, ge=1, le=100)
    interval_minutes: int = Field(default=60, ge=5, le=1440, env="YT_INTERVAL_MINUTES")
    
    # Enhanced options
    enabled: bool = Field(default=True)
    days_back: int = Field(default=7, ge=1, le=30)
    use_date_range: bool = Field(default=True)
    
    # Duration filtering
    filter_by_duration: bool = Field(default=True)
    min_duration_seconds: int = Field(default=15, ge=1, le=3600)
    max_duration_seconds: int = Field(default=7200, ge=60, le=28800)
    
    # Scheduler settings
    max_instances: int = Field(default=1, ge=1, le=5)
    coalesce: bool = Field(default=True)
    misfire_grace_time: int = Field(default=300, ge=60, le=3600)
    
    class Config:
        env_prefix = "YT_"
        env_file = ".env"
        extra = "ignore"


class ClassificationAPISettings(BaseSettings):
    """External classification API configuration"""
    news_api_url: str = Field(
        default="http://localhost:8000/api/v1/content-classification/classify-batch",
        env="CLASSIFICATION_API_URL"
    )
    youtube_api_url: str = Field(
        default="http://localhost:8000/api/v1/youtube/classify-batch",
        env="YOUTUBE_CLASSIFICATION_API_URL"
    )
    timeout_seconds: int = Field(default=240, ge=5, le=3000, env="CLASSIFICATION_TIMEOUT")
    
    class Config:
        env_prefix = "CLASSIFICATION_"
        env_file = ".env"
        extra = "ignore"


class YouTubeAPISettings(BaseSettings):
    """YouTube Data API configuration"""
    api_key: Optional[str] = Field(default="AIzaSyCha7lFiwYVkN_Z4XcUyRD_h5gxzZ-EnU0", env="YOUTUBE_API_KEY")
    quota_limit: int = Field(default=10000, ge=1000, le=50000)
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class AppSettings(BaseSettings):
    """Main application configuration"""
    app_name: str = Field(default="Unified Scraping Service")
    debug: bool = Field(default=False, env="DEBUG")
    host: str = Field(default="127.0.0.1", env="HOST")
    port: int = Field(default=8000, env="PORT")
    reload: bool = Field(default=False, env="RELOAD")
    
    # API Configuration
    api_v1_prefix: str = "/api/v1"
    docs_url: str = "/"
    redoc_url: str = "/redoc"
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    log_file: Optional[str] = Field(default="logs/scraper.log", env="LOG_FILE")
    console_logging: bool = Field(default=False, env="CONSOLE_LOGGING")
    
    class Config:
        env_prefix = "APP_"
        env_file = ".env"
        extra = "ignore"


class Settings(BaseSettings):
    """Master settings combining all configuration sections"""
    app: AppSettings = AppSettings()
    database: DatabaseSettings = DatabaseSettings()
    news_scheduler: NewsSchedulerSettings = NewsSchedulerSettings()
    youtube_scheduler: YouTubeSchedulerSettings = YouTubeSchedulerSettings()
    classification_api: ClassificationAPISettings = ClassificationAPISettings()
    youtube_api: YouTubeAPISettings = YouTubeAPISettings()
    
    class Config:
        # Allow loading from .env file
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance"""
    return settings


def reload_settings():
    """Reload settings from environment/file"""
    global settings
    settings = Settings()
    return settings