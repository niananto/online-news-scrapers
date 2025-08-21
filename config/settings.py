"""
Unified Configuration Management for Scraping Service

This module provides centralized configuration using Pydantic Settings,
replacing scattered configuration across multiple files.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
import os
from dotenv import load_dotenv

# Load .env file explicitly
load_dotenv()


class DatabaseSettings(BaseSettings):
    """Database configuration settings"""
    host: str = Field(default=None, alias="DB_HOST")
    database: str = Field(default=None, alias="DB_DATABASE") 
    user: str = Field(default=None, alias="DB_USER")
    password: str = Field(default=None, alias="DB_PASSWORD")
    port: int = Field(default=5432, alias="DB_PORT")


class NewsSchedulerSettings(BaseSettings):
    """News scraping scheduler configuration"""
    outlets: List[str] = Field(default=[
        'hindustan_times', 'business_standard', 'news18', 'firstpost',
        'republic_world', 'india_dotcom', 'statesman', 'daily_pioneer'
        'south_asia_monitor', 'economic_times', 'india_today', 'ndtv',
        'the_tribune', 'indian_express', 'millennium_post', 'times_of_india',
        'deccan_herald', 'abp_live', 'the_quint', 'the_guardian',
        'washington_post', 'wion', 'telegraph_india', 'the_hindu',
        'bbc', 'cnn', 'aljazeera', 'new_york_times', 'reuters', 'the_diplomat'
    ])
    keyword: str = Field(default="bangladesh", alias="NEWS_KEYWORD")
    limit: int = Field(default=5, ge=1, le=500, alias="NEWS_LIMIT")
    page_size: int = Field(default=25, ge=1, le=100, alias="NEWS_PAGE_SIZE")
    interval_minutes: int = Field(default=60, ge=5, le=1440, alias="NEWS_INTERVAL_MINUTES")
    
    # Enhanced scheduler options
    max_instances: int = Field(default=1, ge=1, le=5)
    coalesce: bool = Field(default=True)
    misfire_grace_time: int = Field(default=60, ge=60, le=3600)
    jitter: int = Field(default=10, ge=0, le=60)
    max_retries_per_outlet: int = Field(default=2, ge=0, le=10)
    timeout_per_outlet: int = Field(default=180, ge=30, le=600)
    circuit_breaker_threshold: int = Field(default=5, ge=1, le=20)


class YouTubeSchedulerSettings(BaseSettings):
    """YouTube scraping scheduler configuration"""
    channels: List[str] = Field(default=[
        '@Firstpost', '@CNN', '@BBCNews' , '@WION', '@TheStatesman' , '@indianexpress' ,
        '@HT-Videos', '@TheHinduOfficial', '@RepublicWorld' , '@nytimes' , '@theGuardian' , 
        '@TheQuint', '@timesofindia', '@indiadotcom', '@NDTV' , '@Thediplomatmagazine',
        '@ThePioneer.' , '@TheTribunechd' , '@businessstandard' , '@TheEconomicTimes' ,
        '@thetelegraphindiaonline' , '@indiatoday' , '@news18india' , '@abp_live' , 
        '@WashingtonPost' , '@aljazeeraenglish' , '@DeccanHerald' , '@Reuters'
    ])
    max_results_per_channel: int = Field(default=10, ge=1, le=200, alias="YT_MAX_RESULTS")
    keywords: Optional[List[str]] = Field(default=[
        'bangladesh', 'sheikh hasina', 'Razakars', 'SaveSecularBangladesh', 'Yunus' , 'jamaat' ,
        # 'StopHinduPersecution' , 'bangladesh AND India' , 'Bangladesh AND Pakistan' , 
        'Bangladesh AND Hindu' , 'Bangladesh AND islamists' , 'Bangladesh AND Minorities' 
    ])
    hashtags: Optional[List[str]] = Field(default=[])
    include_comments: bool = Field(default=True)
    include_transcripts: bool = Field(default=True)
    comments_limit: int = Field(default=20, ge=1, le=100)
    interval_minutes: int = Field(default=180, ge=5, le=1440, alias="YT_INTERVAL_MINUTES")
    
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


class ClassificationAPISettings(BaseSettings):
    """External classification API configuration"""
    news_api_url: str = Field(
        default="http://localhost:8000/api/v1/content-classification/classify-batch",
        alias="CLASSIFICATION_API_URL"
    )
    youtube_api_url: str = Field(
        default="http://localhost:8000/api/v1/youtube/classify-batch",
        alias="YOUTUBE_CLASSIFICATION_API_URL"
    )
    timeout_seconds: int = Field(default=30, ge=5, le=3000, alias="CLASSIFICATION_TIMEOUT")


class YouTubeAPISettings(BaseSettings):
    """YouTube Data API configuration with multi-key support"""
    # Single key support (backward compatibility)
    api_key: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY")
    
    # Multi-key support (2-3 keys)
    api_key_1: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY_1")
    api_key_2: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY_2")
    api_key_3: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY_3")
    
    # Quota configuration
    quota_limit: int = Field(default=10000, ge=1000, le=50000, alias="YOUTUBE_QUOTA_PER_KEY")
    enable_multi_key: bool = Field(default=True, alias="YOUTUBE_ENABLE_MULTI_KEY")
    
    def get_api_keys(self) -> List[str]:
        """
        Get all available API keys.
        Returns multi-keys if available, otherwise falls back to single key.
        """
        keys = []
        
        # Check for multi-key configuration first
        if self.enable_multi_key:
            if self.api_key_1:
                keys.append(self.api_key_1)
            if self.api_key_2:
                keys.append(self.api_key_2)
            if self.api_key_3:
                keys.append(self.api_key_3)
        
        # Fall back to single key if no multi-keys found
        if not keys and self.api_key:
            keys.append(self.api_key)
        
        return keys


class AppSettings(BaseSettings):
    """Main application configuration"""
    app_name: str = Field(default="Unified Scraping Service")
    debug: bool = Field(default=False, alias="DEBUG")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    reload: bool = Field(default=False, alias="RELOAD")
    
    # API Configuration
    api_v1_prefix: str = "/api/v1"
    docs_url: str = "/"
    redoc_url: str = "/redoc"
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    log_file: Optional[str] = Field(default="logs/scraper.log", alias="LOG_FILE")
    console_logging: bool = Field(default=False, alias="CONSOLE_LOGGING")


class Settings(BaseSettings):
    """Master settings combining all configuration sections"""
    app: AppSettings = AppSettings()
    database: DatabaseSettings = DatabaseSettings()
    news_scheduler: NewsSchedulerSettings = NewsSchedulerSettings()
    youtube_scheduler: YouTubeSchedulerSettings = YouTubeSchedulerSettings()
    classification_api: ClassificationAPISettings = ClassificationAPISettings()
    youtube_api: YouTubeAPISettings = YouTubeAPISettings()
    
    class Config:
        # This is the only Config we need, at the top level
        extra = "ignore"  # Ignore extra environment variables


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
