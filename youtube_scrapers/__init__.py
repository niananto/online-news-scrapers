"""
YouTube Scrapers Module

This module provides YouTube video extraction capabilities using the YouTube Data API v3
and transcript extraction via yt-dlp. Unlike news scrapers, YouTube uses a single
scraper implementation that works across all channels.
"""

from .base import BaseYouTubeScraper
from .channel_scraper import YouTubeChannelScraper

__all__ = ['BaseYouTubeScraper', 'YouTubeChannelScraper']