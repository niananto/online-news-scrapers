"""
Database Configuration and Connection Management

Provides database connection utilities and connection pooling
for both news and YouTube content operations.
"""

import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from typing import Optional, Generator
import logging

from .settings import get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Database connection manager with connection pooling
    """
    
    def __init__(self):
        self.settings = get_settings().database
        self._connection_pool: Optional[psycopg2.pool.SimpleConnectionPool] = None
        
    def initialize_pool(self, min_connections: int = 1, max_connections: int = 10):
        """
        Initialize the database connection pool
        
        Args:
            min_connections: Minimum number of connections to maintain
            max_connections: Maximum number of connections allowed
        """
        try:
            self._connection_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=min_connections,
                maxconn=max_connections,
                host=self.settings.host,
                database=self.settings.database,
                user=self.settings.user,
                password=self.settings.password,
                port=self.settings.port
            )
            logger.info(f"Database connection pool initialized: {min_connections}-{max_connections} connections")
            
        except Exception as e:
            logger.error(f"Failed to initialize database connection pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        """
        Get a database connection from the pool with automatic cleanup
        
        Yields:
            Database connection
        """
        if not self._connection_pool:
            self.initialize_pool()
            
        connection = None
        try:
            connection = self._connection_pool.getconn()
            if connection:
                yield connection
        except Exception as e:
            if connection:
                connection.rollback()
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if connection:
                self._connection_pool.putconn(connection)
    
    def get_direct_connection(self) -> psycopg2.extensions.connection:
        """
        Get a direct database connection (not from pool)
        
        Returns:
            Database connection
        """
        return psycopg2.connect(
            host=self.settings.host,
            database=self.settings.database,
            user=self.settings.user,
            password=self.settings.password,
            port=self.settings.port
        )
    
    def test_connection(self) -> bool:
        """
        Test database connectivity
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    return result[0] == 1
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    def close_pool(self):
        """Close all connections in the pool"""
        if self._connection_pool:
            self._connection_pool.closeall()
            logger.info("Database connection pool closed")
    
    def get_pool_status(self) -> dict:
        """
        Get connection pool status information
        
        Returns:
            Dictionary with pool status information
        """
        if not self._connection_pool:
            return {"status": "not_initialized"}
            
        return {
            "status": "active",
            "min_connections": self._connection_pool.minconn,
            "max_connections": self._connection_pool.maxconn,
            "closed": self._connection_pool.closed
        }


# Global database manager instance
db_manager = DatabaseManager()


def get_db_manager() -> DatabaseManager:
    """Get the global database manager instance"""
    return db_manager


@contextmanager
def get_db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Convenience function to get a database connection
    
    Yields:
        Database connection
    """
    with db_manager.get_connection() as connection:
        yield connection