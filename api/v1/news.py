"""
News API Endpoints

REST API endpoints for news scraping operations including
manual scraping, outlet management, and content retrieval.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import List, Dict, Any

from models.news import (
    NewsScrapeRequest, NewsMultiScrapeRequest, ArticleModel,
    NewsScrapeResponse, NewsOutletStatus
)
from services.news_service import NewsService
from api.dependencies import (
    get_news_service, validate_outlet, validate_outlets, setup_request_context
)
from core.logging import get_api_logger
from core.exceptions import ScrapingError, create_error_response

logger = get_api_logger()
router = APIRouter(prefix="/news", tags=["News Scraping"])


@router.post("/scrape", response_model=List[ArticleModel])
async def scrape_single_outlet(
    request: NewsScrapeRequest,
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Scrape articles from a single news outlet
    
    This endpoint scrapes articles from the specified outlet and returns them
    immediately without storing in the database. Use this for quick testing
    or when you need articles in real-time.
    """
    try:
        logger.info(f"Scraping single outlet: {request.outlet}")
        
        # Validate outlet
        outlet = validate_outlet(request.outlet, news_service)
        
        # Scrape articles
        articles = await news_service.scrape_outlet(
            outlet=outlet,
            keyword=request.keyword,
            limit=request.limit,
            page_size=request.page_size
        )
        
        # Convert to response models
        return [
            ArticleModel(
                title=article.title,
                published_at=article.published_at,
                url=article.url,
                content=article.content,
                summary=article.summary,
                author=article.author,
                outlet=article.outlet,
                tags=article.tags,
                section=article.section
            )
            for article in articles
        ]
        
    except ScrapingError as e:
        logger.error(f"Scraping failed: {e.message}")
        return create_error_response(e)
    except Exception as e:
        logger.error(f"Unexpected error in scrape_single_outlet: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/scrape-and-store", response_model=NewsScrapeResponse)
async def scrape_and_store_outlets(
    request: NewsMultiScrapeRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Scrape multiple outlets and store results in database
    
    This endpoint scrapes articles from multiple outlets concurrently,
    stores them in the database with deduplication, and calls the
    classification API for content analysis.
    """
    try:
        logger.info(f"Scraping and storing {len(request.outlets)} outlets")
        
        # Validate outlets
        outlets = validate_outlets(request.outlets, news_service)
        
        # Execute scraping and storage
        result = await news_service.scrape_multiple_outlets(
            outlets=outlets,
            keyword=request.keyword,
            limit=request.limit,
            page_size=request.page_size,
            max_concurrent=request.max_concurrent
        )
        
        return NewsScrapeResponse(**result)
        
    except Exception as e:
        logger.error(f"Error in scrape_and_store_outlets: {e}")
        raise HTTPException(status_code=500, detail=f"Scraping operation failed: {str(e)}")


@router.get("/outlets")
async def list_available_outlets(
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Get list of available news outlets
    
    Returns all supported news outlets that can be scraped.
    Use these outlet names in other API endpoints.
    """
    outlets = news_service.get_available_outlets()
    return {
        "outlets": sorted(outlets),
        "total": len(outlets),
        "description": "Available news outlets for scraping"
    }


@router.get("/outlets/status")
async def get_outlet_status(
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Get status information for all news outlets
    
    Returns circuit breaker states, failure counts, and availability
    status for all news outlets. Use this to monitor outlet health.
    """
    try:
        status_info = news_service.get_outlet_status()
        
        # Convert to response models
        formatted_status = {}
        for outlet, info in status_info.items():
            formatted_status[outlet] = NewsOutletStatus(**info)
        
        return {
            "outlet_status": formatted_status,
            "summary": {
                "total_outlets": len(formatted_status),
                "available_outlets": len([s for s in formatted_status.values() if s.available]),
                "failed_outlets": len([s for s in formatted_status.values() if s.failure_count > 0])
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting outlet status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get outlet status: {str(e)}")


@router.post("/outlets/{outlet}/reset-failures")
async def reset_outlet_failures(
    outlet: str,
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Reset failure count and circuit breaker for a specific outlet
    
    Use this endpoint to manually reset the circuit breaker and failure
    count for an outlet that has been marked as failing.
    """
    try:
        # Validate outlet
        outlet = validate_outlet(outlet, news_service)
        
        # Reset failures
        news_service.reset_outlet_failures(outlet)
        
        return {
            "message": f"Failures reset for outlet: {outlet}",
            "outlet": outlet,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Error resetting failures for {outlet}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset failures: {str(e)}")


@router.post("/reset-all-failures")
async def reset_all_outlet_failures(
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Reset failure counts and circuit breakers for all outlets
    
    Use this endpoint to clear all failure states and reset circuit
    breakers for all news outlets.
    """
    try:
        news_service.reset_outlet_failures()
        
        return {
            "message": "All outlet failures reset successfully",
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Error resetting all outlet failures: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset all failures: {str(e)}")


@router.get("/articles/search")
async def search_articles(
    query: str,
    limit: int = 50,
    offset: int = 0,
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Search news articles in the database
    
    Performs full-text search across article titles, content, and summaries.
    Use this to find specific articles or topics in your stored content.
    """
    try:
        # Use the database service through news service
        results = news_service.db_service.search_content(
            query=query,
            content_type="news",
            limit=limit
        )
        
        # Apply offset manually since it's not supported in search_content
        paginated_results = results[offset:offset + limit] if offset > 0 else results[:limit]
        
        return {
            "articles": paginated_results,
            "total_found": len(results),
            "returned": len(paginated_results),
            "query": query,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": len(results) > (offset + limit)
            }
        }
        
    except Exception as e:
        logger.error(f"Error searching articles: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/statistics")
async def get_news_statistics(
    _: str = Depends(setup_request_context),
    news_service: NewsService = Depends(get_news_service)
):
    """
    Get news database statistics
    
    Returns statistics about stored news articles including
    counts by platform, recent activity, and storage metrics.
    """
    try:
        # Get article counts by platform
        article_counts = news_service.db_service.get_article_count_by_platform()
        total_articles = sum(article_counts.values())
        
        return {
            "statistics": {
                "total_articles": total_articles,
                "articles_by_platform": article_counts,
                "platforms_count": len(article_counts),
                "top_platforms": sorted(
                    article_counts.items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )[:10]
            },
            "database_health": news_service.db_service.get_database_health()
        }
        
    except Exception as e:
        logger.error(f"Error getting news statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")