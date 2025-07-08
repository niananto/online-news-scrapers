from .base import BaseNewsScraper
from .hindustan_times import HindustanTimesScraper
from .business_standard import BusinessStandardScraper
from .news18 import News18Scraper
from .firstpost import FirstpostScraper

__all__ = [
    "HindustanTimesScraper",
    "BusinessStandardScraper",
    "News18Scraper",
    "FirstpostScraper",
]