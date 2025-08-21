"""
News Scraping Service

Business logic for news scraping operations, handling multiple outlets
with circuit breaker patterns and comprehensive error handling.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import List, Dict, Any, Optional
import aiohttp
from datetime import datetime

from news_scrapers import *
from news_scrapers.base import Article
from services.database_service import UnifiedDatabaseService
from core.logging import get_scraper_logger, log_performance
from core.exceptions import (
    ScrapingError, APIError, CircuitBreakerError, 
    retry_with_backoff, CircuitBreaker
)
from config.settings import get_settings

logger = get_scraper_logger("news_service")


class NewsService:
    """
    News scraping service handling multiple outlets with advanced error handling
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.db_service = UnifiedDatabaseService()
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Scraper registry mapping outlet names to scraper classes
        self.scraper_map = {
            "hindustan_times": HindustanTimesScraper,
            "business_standard": BusinessStandardScraper,
            "news18": News18Scraper,
            "firstpost": FirstpostScraper,
            "republic_world": RepublicWorldScraper,
            "india_dotcom": IndiaDotComScraper,
            "statesman": StatesmanScraper,
            "daily_pioneer": DailyPioneerScraper,
            "south_asia_monitor": SouthAsiaMonitorScraper,
            "economic_times": EconomicTimesScraper,
            "india_today": IndiaTodayScraper,
            "ndtv": NdtvScraper,
            "the_tribune": TheTribuneScraper,
            "indian_express": IndianExpressScraper,
            "millennium_post": MillenniumPostScraper,
            "times_of_india": TimesOfIndiaScraper,
            "deccan_herald": DeccanHeraldScraper,
            "abp_live": AbpLiveScraper,
            "the_quint": TheQuintScraper,
            "the_guardian": TheGuardianScraper,
            "washington_post": WashingtonPostScraper,
            "wion": WionScraper,
            "telegraph_india": TelegraphIndiaScraper,
            "the_hindu": TheHinduScraper,
            "bbc": BBCScraper,
            "cnn": CNNScraper,
            "aljazeera": AljazeeraScraper,
            "new_york_times": NewYorkTimesScraper,
            "reuters": ReutersScraper,
            "the_diplomat": TheDiplomatScraper,
        }
        
        # Circuit breakers for each outlet
        self.circuit_breakers = {
            outlet: CircuitBreaker(
                failure_threshold=self.settings.news_scheduler.circuit_breaker_threshold,
                recovery_timeout=300  # 5 minutes
            )
            for outlet in self.scraper_map.keys()
        }
        
        # Failure tracking for scheduler integration
        self.failure_counts = {}
    
    def get_available_outlets(self) -> List[str]:
        """Get list of available news outlets"""
        return list(self.scraper_map.keys())
    
    async def scrape_outlet(
        self, 
        outlet: str, 
        keyword: str = "bangladesh",
        limit: int = 30,
        page_size: int = 50,
        timeout: int = 180
    ) -> List[Article]:
        """
        Scrape articles from a single news outlet
        
        Args:
            outlet: Name of the news outlet
            keyword: Search keyword
            limit: Maximum number of articles
            page_size: Articles per page
            timeout: Operation timeout in seconds
            
        Returns:
            List of Article objects
            
        Raises:
            ScrapingError: When scraping fails
        """
        if outlet not in self.scraper_map:
            raise ScrapingError(outlet, f"Unknown outlet: {outlet}")
        
        scraper_cls = self.scraper_map[outlet]
        
        try:
            with log_performance(logger, f"scraping {outlet} for '{keyword}'"):
                # Execute scraping with timeout
                articles = await asyncio.wait_for(
                    self._run_scraper_async(scraper_cls, keyword, limit, page_size),
                    timeout=timeout
                )
                
                # Deduplicate by URL
                unique_articles = self._deduplicate_articles(articles)
                
                logger.info(f"Scraped {len(articles)} articles from {outlet}, "
                          f"{len(unique_articles)} unique")
                
                return unique_articles
                
        except asyncio.TimeoutError:
            error_msg = f"Timeout after {timeout}s"
            logger.error(f"Scraping timeout for {outlet}: {error_msg}")
            raise ScrapingError(outlet, error_msg)
        except Exception as e:
            logger.error(f"Scraping failed for {outlet}: {e}")
            raise ScrapingError(outlet, str(e))
    
    async def scrape_and_store_outlet(
        self,
        outlet: str,
        keyword: str = "bangladesh", 
        limit: int = 30,
        page_size: int = 50,
        timeout: int = 180
    ) -> Dict[str, Any]:
        """
        Scrape outlet and immediately store results in database
        
        Args:
            outlet: Name of the news outlet
            keyword: Search keyword
            limit: Maximum number of articles
            page_size: Articles per page
            timeout: Operation timeout in seconds
            
        Returns:
            Dictionary with scraping and storage statistics
        """
        try:
            # Check circuit breaker
            circuit_breaker = self.circuit_breakers.get(outlet)
            if circuit_breaker and circuit_breaker.state == 'OPEN':
                raise CircuitBreakerError(
                    service=outlet,
                    failure_count=circuit_breaker.failure_count,
                    threshold=circuit_breaker.failure_threshold
                )
            
            # Scrape articles
            logger.info(f"[SEARCH] Scraping {outlet} for '{keyword}'...")
            articles = await self.scrape_outlet(outlet, keyword, limit, page_size, timeout)
            
            # Convert to dict format for database
            article_dicts = [asdict(article) for article in articles]
            
            # Store in database
            logger.info(f"[SAVE] Inserting {len(article_dicts)} articles from {outlet}...")
            storage_stats = self.db_service.insert_articles_to_db(article_dicts, outlet)
            
            # Call classification API if articles were inserted
            classification_result = {"successful": 0, "failed": 0}
            if storage_stats["inserted"] > 0 and storage_stats.get("inserted_ids"):
                classification_result = await self._classify_articles(storage_stats["inserted_ids"])
            
            # Reset circuit breaker on success
            if circuit_breaker:
                circuit_breaker.on_success()
            self.failure_counts[outlet] = 0
            
            return {
                "outlet": outlet,
                "scraped": len(articles),
                "unique": len(article_dicts),
                "inserted": storage_stats["inserted"],
                "duplicates_skipped": storage_stats["duplicates_skipped"],
                "errors": storage_stats["errors"],
                "classified": classification_result.get("successful", 0),
                "classification_failed": classification_result.get("failed", 0),
                "status": "success"
            }
            
        except (ScrapingError, CircuitBreakerError) as e:
            # Handle expected errors
            if circuit_breaker:
                circuit_breaker.on_failure()
            self.failure_counts[outlet] = self.failure_counts.get(outlet, 0) + 1
            
            logger.error(f"Scraping failed for {outlet}: {e.message}")
            return {
                "outlet": outlet,
                "error": e.message,
                "scraped": 0,
                "unique": 0,
                "inserted": 0,
                "duplicates_skipped": 0,
                "errors": 1,
                "classified": 0,
                "classification_failed": 0,
                "status": "error"
            }
        except Exception as e:
            # Handle unexpected errors
            if circuit_breaker:
                circuit_breaker.on_failure()
            self.failure_counts[outlet] = self.failure_counts.get(outlet, 0) + 1
            
            logger.error(f"Unexpected error for {outlet}: {e}")
            return {
                "outlet": outlet,
                "error": str(e),
                "scraped": 0,
                "unique": 0,
                "inserted": 0,
                "duplicates_skipped": 0,
                "errors": 1,
                "classified": 0,
                "classification_failed": 0,
                "status": "error"
            }
    
    @retry_with_backoff(max_retries=2)
    async def scrape_outlet_with_retry(
        self,
        outlet: str,
        keyword: str = "bangladesh",
        limit: int = 30,
        page_size: int = 50
    ) -> Dict[str, Any]:
        """
        Scrape outlet with automatic retry logic
        
        Args:
            outlet: Name of the news outlet
            keyword: Search keyword  
            limit: Maximum number of articles
            page_size: Articles per page
            
        Returns:
            Dictionary with scraping results
        """
        timeout = self.settings.news_scheduler.timeout_per_outlet
        return await self.scrape_and_store_outlet(outlet, keyword, limit, page_size, timeout)
    
    async def scrape_multiple_outlets(
        self,
        outlets: List[str],
        keyword: str = "bangladesh",
        limit: int = 30,
        page_size: int = 50,
        max_concurrent: int = 3
    ) -> Dict[str, Any]:
        """
        Scrape multiple outlets concurrently with rate limiting
        
        Args:
            outlets: List of outlet names
            keyword: Search keyword
            limit: Maximum articles per outlet
            page_size: Articles per page
            max_concurrent: Maximum concurrent scraping operations
            
        Returns:
            Dictionary with comprehensive results
        """
        logger.info(f"[START] Starting batch scraping for {len(outlets)} outlets")
        
        # Create semaphore to limit concurrent operations
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(outlet):
            async with semaphore:
                return await self.scrape_outlet_with_retry(outlet, keyword, limit, page_size)
        
        # Execute all scraping operations
        results = await asyncio.gather(
            *[scrape_with_semaphore(outlet) for outlet in outlets],
            return_exceptions=True
        )
        
        # Process results and handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Scraping failed for {outlets[i]}: {result}")
                processed_results.append({
                    "outlet": outlets[i],
                    "error": str(result),
                    "scraped": 0,
                    "inserted": 0,
                    "status": "error"
                })
            else:
                processed_results.append(result)
        
        # Calculate summary statistics
        summary = self._calculate_batch_summary(processed_results)
        
        logger.info(f"🎯 Batch scraping complete: {summary['total_inserted']} articles, {summary['successful_outlets']}/{len(processed_results)} outlets successful")
        
        return {
            "summary": summary,
            "results": processed_results,
            "timestamp": datetime.now().isoformat()
        }
    
    # =============================================================================
    # Private Helper Methods
    # =============================================================================
    
    async def _run_scraper_async(
        self,
        scraper_cls,
        keyword: str,
        limit: int,
        page_size: int
    ) -> List[Article]:
        """Run scraper in thread pool executor"""
        def _blocking_scraper_call():
            scraper = scraper_cls()
            collected = []
            page = 1
            
            while len(collected) < limit:
                requested = min(page_size, limit - len(collected))
                batch = scraper.search(keyword, page=page, size=requested)
                if not batch:
                    break
                collected.extend(batch)
                page += 1
            
            return collected[:limit]
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, _blocking_scraper_call)
    
    def _deduplicate_articles(self, articles: List[Article]) -> List[Article]:
        """Remove duplicate articles based on URL"""
        seen_urls = set()
        unique_articles = []
        
        for article in articles:
            if article.url and article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)
        
        return unique_articles
    
    async def _classify_articles(self, content_ids: List[str]) -> Dict[str, Any]:
        """
        Call classification API for article classification
        
        Args:
            content_ids: List of article content IDs
            
        Returns:
            Dictionary with classification results
        """
        if not content_ids:
            return {"successful": 0, "failed": 0}
        
        try:
            timeout = aiohttp.ClientTimeout(total=self.settings.classification_api.timeout_seconds)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                payload = {"content_ids": content_ids}
                
                logger.info(f"[AI] Calling classification API for {len(content_ids)} articles...")
                
                async with session.post(
                    self.settings.classification_api.news_api_url,
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        total_classified = result.get('total_classified', 0)
                        failed_count = len(content_ids) - total_classified
                        
                        logger.info(f"[OK] Classification: {total_classified} successful, "
                                  f"{failed_count} failed")
                        
                        return {
                            "successful": total_classified,
                            "failed": failed_count,
                            "total_classified": total_classified
                        }
                    elif response.status == 202:
                        # Accepted for async processing - this is a success!
                        result = await response.json()
                        logger.info(f"[OK] Classification API accepted {len(content_ids)} articles for async processing")
                        return {
                            "successful": len(content_ids),
                            "failed": 0,
                            "total_classified": len(content_ids)
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Classification API error {response.status}: {error_text}")
                        return {"successful": 0, "failed": len(content_ids)}
                        
        except Exception as e:
            logger.error(f"Classification API exception: {e}")
            return {"successful": 0, "failed": len(content_ids)}
    
    def _calculate_batch_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate summary statistics for batch operation"""
        total_scraped = sum(r.get("scraped", 0) for r in results)
        total_inserted = sum(r.get("inserted", 0) for r in results)
        total_duplicates = sum(r.get("duplicates_skipped", 0) for r in results)
        total_errors = sum(r.get("errors", 0) for r in results)
        total_classified = sum(r.get("classified", 0) for r in results)
        successful_outlets = len([r for r in results if r.get("status") == "success"])
        failed_outlets = len(results) - successful_outlets
        
        return {
            "outlets_processed": len(results),
            "successful_outlets": successful_outlets,
            "failed_outlets": failed_outlets,
            "total_scraped": total_scraped,
            "total_inserted": total_inserted,
            "total_duplicates": total_duplicates,
            "total_errors": total_errors,
            "total_classified": total_classified
        }
    
    def get_outlet_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status information for all outlets"""
        status = {}
        
        for outlet in self.scraper_map.keys():
            circuit_breaker = self.circuit_breakers.get(outlet)
            failure_count = self.failure_counts.get(outlet, 0)
            
            status[outlet] = {
                "available": True,
                "circuit_breaker_state": circuit_breaker.state if circuit_breaker else "CLOSED",
                "failure_count": failure_count,
                "last_error": None  # Could be enhanced to track last errors
            }
        
        return status
    
    def reset_outlet_failures(self, outlet: str = None):
        """Reset failure counts and circuit breakers for specific outlet or all"""
        if outlet:
            if outlet in self.failure_counts:
                self.failure_counts[outlet] = 0
            if outlet in self.circuit_breakers:
                self.circuit_breakers[outlet].on_success()
            logger.info(f"Reset failures for outlet: {outlet}")
        else:
            self.failure_counts.clear()
            for cb in self.circuit_breakers.values():
                cb.on_success()
            logger.info("Reset failures for all outlets")
    
    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)