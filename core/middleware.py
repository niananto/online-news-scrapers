"""
FastAPI Middleware for Cross-cutting Concerns

Provides middleware for logging, correlation IDs, error handling,
and performance monitoring.
"""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.logging import set_correlation_id, clear_correlation_id, get_logger


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add correlation IDs to requests for distributed tracing
    """
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Get correlation ID from header or generate new one
        correlation_id = request.headers.get('X-Correlation-ID') or str(uuid.uuid4())
        
        # Set correlation ID in context
        set_correlation_id(correlation_id)
        
        try:
            response = await call_next(request)
            
            # Add correlation ID to response headers
            response.headers['X-Correlation-ID'] = correlation_id
            
            return response
        finally:
            # Clear correlation ID from context
            clear_correlation_id()


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request/response logging
    """
    
    def __init__(self, app, logger_name: str = "api.middleware"):
        super().__init__(app)
        self.logger = get_logger(logger_name)
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        
        # Log incoming request
        self.logger.info(
            f"Incoming request: {request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "query_params": str(request.query_params),
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent")
            }
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate response time
            process_time = time.time() - start_time
            
            # Log response
            self.logger.info(
                f"Request completed: {request.method} {request.url.path} -> {response.status_code}",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "process_time": round(process_time, 4)
                }
            )
            
            # Add performance header
            response.headers["X-Process-Time"] = str(round(process_time, 4))
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            
            self.logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "process_time": round(process_time, 4),
                    "error": str(e)
                },
                exc_info=True
            )
            raise


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to responses
    """
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        
        # Add security headers
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": "default-src 'self'",
        }
        
        for header, value in security_headers.items():
            response.headers[header] = value
        
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple rate limiting middleware based on client IP
    """
    
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.client_requests = {}
        self.logger = get_logger("api.ratelimit")
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()
        
        # Clean old entries (older than 1 minute)
        minute_ago = current_time - 60
        self.client_requests = {
            ip: timestamps for ip, timestamps in self.client_requests.items()
            if any(ts > minute_ago for ts in timestamps)
        }
        
        # Get client's request history
        client_history = self.client_requests.get(client_ip, [])
        
        # Filter requests from the last minute
        recent_requests = [ts for ts in client_history if ts > minute_ago]
        
        # Check rate limit
        if len(recent_requests) >= self.requests_per_minute:
            self.logger.warning(
                f"Rate limit exceeded for client {client_ip}",
                extra={"client_ip": client_ip, "request_count": len(recent_requests)}
            )
            
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "type": "RateLimitExceeded",
                        "message": f"Rate limit of {self.requests_per_minute} requests per minute exceeded",
                        "details": {"retry_after": 60}
                    }
                },
                headers={"Retry-After": "60"}
            )
        
        # Record this request
        recent_requests.append(current_time)
        self.client_requests[client_ip] = recent_requests
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        remaining = max(0, self.requests_per_minute - len(recent_requests))
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(current_time + 60))
        
        return response


class HealthCheckMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle health check requests efficiently
    """
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Fast path for health checks
        if request.url.path in ["/health", "/api/v1/health", "/healthz", "/ready"]:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                content={"status": "healthy", "timestamp": time.time()},
                headers={"Cache-Control": "no-cache"}
            )
        
        return await call_next(request)


class CORSMiddleware(BaseHTTPMiddleware):
    """
    Custom CORS middleware with configuration
    """
    
    def __init__(self, app, allow_origins: list = None, allow_methods: list = None,
                 allow_headers: list = None, allow_credentials: bool = False):
        super().__init__(app)
        self.allow_origins = allow_origins or ["*"]
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        self.allow_headers = allow_headers or ["*"]
        self.allow_credentials = allow_credentials
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Handle preflight requests
        if request.method == "OPTIONS":
            from fastapi.responses import Response as FastAPIResponse
            response = FastAPIResponse()
        else:
            response = await call_next(request)
        
        # Add CORS headers
        origin = request.headers.get("origin")
        if origin and (self.allow_origins == ["*"] or origin in self.allow_origins):
            response.headers["Access-Control-Allow-Origin"] = origin
        elif self.allow_origins == ["*"]:
            response.headers["Access-Control-Allow-Origin"] = "*"
        
        response.headers["Access-Control-Allow-Methods"] = ", ".join(self.allow_methods)
        response.headers["Access-Control-Allow-Headers"] = ", ".join(self.allow_headers)
        
        if self.allow_credentials:
            response.headers["Access-Control-Allow-Credentials"] = "true"
        
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect basic metrics
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.request_count = 0
        self.request_duration_sum = 0.0
        self.status_codes = {}
        self.logger = get_logger("api.metrics")
    
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            # Update metrics
            self.request_count += 1
            duration = time.time() - start_time
            self.request_duration_sum += duration
            
            status_code = response.status_code
            self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
            
            # Log slow requests
            if duration > 5.0:  # Log requests taking more than 5 seconds
                self.logger.warning(
                    f"Slow request detected: {request.method} {request.url.path}",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "duration": round(duration, 4),
                        "status_code": status_code
                    }
                )
            
            return response
            
        except Exception as e:
            # Update error metrics
            self.request_count += 1
            duration = time.time() - start_time
            self.request_duration_sum += duration
            self.status_codes[500] = self.status_codes.get(500, 0) + 1
            
            raise
    
    def get_metrics(self) -> dict:
        """Get current metrics"""
        avg_duration = (self.request_duration_sum / self.request_count 
                       if self.request_count > 0 else 0)
        
        return {
            "total_requests": self.request_count,
            "average_duration": round(avg_duration, 4),
            "status_code_distribution": self.status_codes.copy()
        }