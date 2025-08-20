"""
Centralized Logging Configuration

Provides structured logging setup with correlation IDs and
different output formats for development and production.
"""

import logging
import logging.config
import sys
import uuid
from contextvars import ContextVar
from typing import Dict, Any, Optional
import json
from datetime import datetime

from config.settings import get_settings

# Context variable for request correlation IDs
correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class CorrelationIdFilter(logging.Filter):
    """Add correlation ID to log records"""
    
    def filter(self, record):
        record.correlation_id = correlation_id.get() or 'no-correlation-id'
        return True


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging"""
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'correlation_id': getattr(record, 'correlation_id', 'no-correlation-id'),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ('name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'lineno', 'funcName', 'created',
                          'msecs', 'relativeCreated', 'thread', 'threadName',
                          'processName', 'process', 'message', 'exc_info',
                          'exc_text', 'stack_info', 'correlation_id'):
                log_entry[key] = value
        
        return json.dumps(log_entry)


class ReadableFormatter(logging.Formatter):
    """Readable multi-line formatter without colors"""
    
    def format(self, record):
        # Create separator line
        separator = "=" * 60
        
        # Build readable log entry
        lines = [
            f"\n{separator}",
            f"TIMESTAMP: {datetime.utcnow().isoformat()}Z",
            f"LEVEL: {record.levelname}",
            f"LOGGER: {record.name}",
            f"MESSAGE: {record.getMessage()}",
            f"CORRELATION_ID: {getattr(record, 'correlation_id', 'no-correlation-id')}",
            f"MODULE: {record.module}",
            f"FUNCTION: {record.funcName}",
            f"LINE: {record.lineno}",
        ]
        
        # Add exception info if present
        if record.exc_info:
            lines.append(f"EXCEPTION: {self.formatException(record.exc_info)}")
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ('name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'lineno', 'funcName', 'created',
                          'msecs', 'relativeCreated', 'thread', 'threadName',
                          'processName', 'process', 'message', 'exc_info',
                          'exc_text', 'stack_info', 'correlation_id'):
                lines.append(f"{key.upper()}: {value}")
        
        lines.append(separator)
        
        return "\n".join(lines)


class ColoredFormatter(logging.Formatter):
    """Colored console formatter for development"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        
        # Add correlation ID if available
        correlation_id_str = getattr(record, 'correlation_id', 'no-correlation-id')
        if correlation_id_str != 'no-correlation-id':
            correlation_id_str = f"[{correlation_id_str[:8]}]"
        else:
            correlation_id_str = ""
        
        record.correlation_id_display = correlation_id_str
        
        return super().format(record)


def setup_logging(
    log_level: str = None,
    json_logs: bool = False,
    readable_logs: bool = True,
    log_file: Optional[str] = None
) -> None:
    """
    Setup centralized logging configuration
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: Whether to use JSON formatting
        readable_logs: Whether to use readable multi-line formatting
        log_file: Optional log file path
    """
    settings = get_settings()
    
    if log_level is None:
        log_level = settings.app.log_level
    
    # Clear existing handlers
    logging.root.handlers.clear()
    
    # Configure root logger
    logging.root.setLevel(getattr(logging, log_level.upper()))
    
    # Only add console handler if console_logging is enabled
    if getattr(settings.app, 'console_logging', True):
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.addFilter(CorrelationIdFilter())
        
        if json_logs:
            console_formatter = JSONFormatter()
        elif readable_logs:
            console_formatter = ReadableFormatter()
        else:
            console_formatter = ColoredFormatter(
                '%(asctime)s %(correlation_id_display)s %(levelname)s %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        console_handler.setFormatter(console_formatter)
        logging.root.addHandler(console_handler)
    
    # File handler (optional or primary)
    if log_file:
        # Create directory if it doesn't exist
        import os
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.addFilter(CorrelationIdFilter())
        # Use readable format for file logging like the example
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logging.root.addHandler(file_handler)
    
    # Configure third-party loggers
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    logging.getLogger('uvicorn.error').setLevel(logging.INFO)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('selenium').setLevel(logging.WARNING)
    logging.getLogger('yt-dlp').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def set_correlation_id(correlation_id_value: str = None) -> str:
    """
    Set correlation ID for current context
    
    Args:
        correlation_id_value: Custom correlation ID or None for auto-generated
        
    Returns:
        The correlation ID that was set
    """
    if correlation_id_value is None:
        correlation_id_value = str(uuid.uuid4())
    
    correlation_id.set(correlation_id_value)
    return correlation_id_value


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID"""
    return correlation_id.get()


def clear_correlation_id():
    """Clear current correlation ID"""
    correlation_id.set(None)


# Performance logging helpers
class PerformanceLogger:
    """Helper class for performance logging"""
    
    def __init__(self, logger: logging.Logger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.utcnow()
        self.logger.info(f"[START] Starting {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.utcnow() - self.start_time).total_seconds()
        if exc_type is None:
            self.logger.info(f"[SUCCESS] Completed {self.operation} in {duration:.2f}s")
        else:
            self.logger.error(f"[FAILED] Failed {self.operation} after {duration:.2f}s: {exc_val}")


def log_performance(logger: logging.Logger, operation: str):
    """
    Context manager for performance logging
    
    Args:
        logger: Logger instance to use
        operation: Description of the operation being measured
        
    Returns:
        PerformanceLogger context manager
    """
    return PerformanceLogger(logger, operation)


# Application-specific loggers
def get_scraper_logger(scraper_name: str) -> logging.Logger:
    """Get logger for scraper operations"""
    return get_logger(f"scraper.{scraper_name}")


def get_scheduler_logger() -> logging.Logger:
    """Get logger for scheduler operations"""
    return get_logger("scheduler")


def get_database_logger() -> logging.Logger:
    """Get logger for database operations"""
    return get_logger("database")


def get_api_logger() -> logging.Logger:
    """Get logger for API operations"""
    return get_logger("api")