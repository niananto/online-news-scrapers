"""
Custom Exception Classes and Error Handling

Provides application-specific exceptions and centralized error handling
for different types of failures in the scraping system.
"""

from typing import Any, Dict, Optional, List
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
import logging


class ScrapingServiceException(Exception):
    """Base exception for all scraping service errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ScrapingError(ScrapingServiceException):
    """Exception raised during scraping operations"""
    
    def __init__(self, outlet: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.outlet = outlet
        super().__init__(f"Scraping failed for {outlet}: {message}", details)


class YouTubeScrapingError(ScrapingServiceException):
    """Exception raised during YouTube scraping operations"""
    
    def __init__(self, channel: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.channel = channel
        super().__init__(f"YouTube scraping failed for {channel}: {message}", details)


class DatabaseError(ScrapingServiceException):
    """Exception raised during database operations"""
    
    def __init__(self, operation: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.operation = operation
        super().__init__(f"Database {operation} failed: {message}", details)


class ConfigurationError(ScrapingServiceException):
    """Exception raised for configuration-related issues"""
    pass


class SchedulerError(ScrapingServiceException):
    """Exception raised during scheduler operations"""
    
    def __init__(self, job_id: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.job_id = job_id
        super().__init__(f"Scheduler error for job {job_id}: {message}", details)


class APIError(ScrapingServiceException):
    """Exception raised during external API calls"""
    
    def __init__(self, api_name: str, status_code: int, message: str, 
                 details: Optional[Dict[str, Any]] = None):
        self.api_name = api_name
        self.status_code = status_code
        super().__init__(f"{api_name} API error ({status_code}): {message}", details)


class ValidationError(ScrapingServiceException):
    """Exception raised for data validation errors"""
    
    def __init__(self, field: str, value: Any, message: str):
        self.field = field
        self.value = value
        super().__init__(f"Validation error for {field}: {message}")


class RateLimitError(ScrapingServiceException):
    """Exception raised when rate limits are exceeded"""
    
    def __init__(self, service: str, retry_after: Optional[int] = None):
        self.service = service
        self.retry_after = retry_after
        message = f"Rate limit exceeded for {service}"
        if retry_after:
            message += f", retry after {retry_after} seconds"
        super().__init__(message)


class CircuitBreakerError(ScrapingServiceException):
    """Exception raised when circuit breaker is open"""
    
    def __init__(self, service: str, failure_count: int, threshold: int):
        self.service = service
        self.failure_count = failure_count
        self.threshold = threshold
        super().__init__(
            f"Circuit breaker open for {service}: {failure_count} failures (threshold: {threshold})"
        )


# HTTP Exception mapping
HTTP_EXCEPTION_MAP = {
    ScrapingError: status.HTTP_503_SERVICE_UNAVAILABLE,
    YouTubeScrapingError: status.HTTP_503_SERVICE_UNAVAILABLE,
    DatabaseError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ConfigurationError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    SchedulerError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    APIError: status.HTTP_502_BAD_GATEWAY,
    ValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    RateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
    CircuitBreakerError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def create_error_response(exception: ScrapingServiceException) -> JSONResponse:
    """
    Create standardized error response for API endpoints
    
    Args:
        exception: The exception that occurred
        
    Returns:
        JSONResponse with error details
    """
    status_code = HTTP_EXCEPTION_MAP.get(type(exception), status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    error_response = {
        "error": {
            "type": exception.__class__.__name__,
            "message": exception.message,
            "details": exception.details
        }
    }
    
    # Add specific fields for different exception types
    if isinstance(exception, (ScrapingError, YouTubeScrapingError)):
        error_response["error"]["source"] = getattr(exception, 'outlet', None) or getattr(exception, 'channel', None)
    elif isinstance(exception, RateLimitError):
        if exception.retry_after:
            error_response["error"]["retry_after"] = exception.retry_after
    elif isinstance(exception, CircuitBreakerError):
        error_response["error"].update({
            "failure_count": exception.failure_count,
            "threshold": exception.threshold
        })
    
    return JSONResponse(
        status_code=status_code,
        content=error_response
    )


# Exception handlers for FastAPI
async def scraping_service_exception_handler(request: Request, exc: ScrapingServiceException):
    """Global exception handler for scraping service exceptions"""
    logger = logging.getLogger("api.exception_handler")
    logger.error(f"Unhandled exception: {exc.message}", extra={"details": exc.details})
    
    return create_error_response(exc)


async def general_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unexpected exceptions"""
    logger = logging.getLogger("api.exception_handler")
    logger.error(f"Unexpected exception: {str(exc)}", exc_info=True)
    
    error_response = {
        "error": {
            "type": "InternalServerError",
            "message": "An unexpected error occurred",
            "details": {}
        }
    }
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response
    )


# Circuit breaker implementation
class CircuitBreaker:
    """
    Circuit breaker pattern implementation for external services
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func, *args, **kwargs):
        """
        Execute function with circuit breaker protection
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: When circuit is open
        """
        import time
        
        if self.state == 'OPEN':
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = 'HALF_OPEN'
            else:
                raise CircuitBreakerError(
                    service=func.__name__,
                    failure_count=self.failure_count,
                    threshold=self.failure_threshold
                )
        
        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise
    
    def on_success(self):
        """Handle successful operation"""
        self.failure_count = 0
        self.state = 'CLOSED'
    
    def on_failure(self):
        """Handle failed operation"""
        import time
        
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'


# Retry decorator with exponential backoff
def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0,
                      exponential_base: float = 2.0, jitter: bool = True):
    """
    Decorator for retrying operations with exponential backoff
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter to delays
    """
    import time
    import random
    import functools
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        break
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    
                    # Add jitter to prevent thundering herd
                    if jitter:
                        delay *= (0.5 + random.random() * 0.5)
                    
                    logger = logging.getLogger(func.__module__)
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                                 f"Retrying in {delay:.2f}s...")
                    
                    time.sleep(delay)
            
            # All retries exhausted
            raise last_exception
        
        return wrapper
    return decorator