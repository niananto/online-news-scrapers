"""
YouTube API Key Pool Manager

Minimal implementation for rotating between 2-3 YouTube API keys
with automatic failover and quota tracking.
"""

import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import hashlib
from threading import Lock

from core.logging import get_logger
from core.exceptions import APIError

logger = get_logger(__name__)


class YouTubeAPIPool:
    """
    Simple API key pool manager for 2-3 YouTube Data API keys.
    
    Features:
    - Round-robin rotation with quota awareness
    - In-memory usage tracking (resets daily)
    - Automatic failover on quota exhaustion
    - Thread-safe operations
    """
    
    # Removed quota cost estimation - using reactive error handling instead
    
    def __init__(self, api_keys: List[str], quota_per_key: int = 10000):
        """
        Initialize the API key pool.
        
        Args:
            api_keys: List of YouTube API keys (2-3 recommended)
            quota_per_key: Daily quota limit per key (default 10000)
        """
        if not api_keys:
            raise ValueError("At least one API key is required")
        
        self.api_keys = api_keys
        self.quota_per_key = quota_per_key
        self.current_index = 0
        self._lock = Lock()
        
        # Initialize usage tracking (simplified - only track exhaustion)
        self.usage = {
            self._hash_key(key): {
                'last_reset': datetime.now().date(),
                'requests_count': 0,
                'last_error': None,
                'is_exhausted': False
            }
            for key in api_keys
        }
        
        logger.info(f"[OK] YouTube API Pool initialized with {len(api_keys)} keys (quota: {quota_per_key} units/key/day)")
    
    def _hash_key(self, api_key: str) -> str:
        """Create a safe hash for logging (don't log actual keys)"""
        return hashlib.md5(api_key.encode()).hexdigest()[:8]
    
    def _reset_if_new_day(self, key_hash: str) -> None:
        """Reset exhaustion status if it's a new day (UTC midnight)"""
        today = datetime.now().date()
        if self.usage[key_hash]['last_reset'] < today:
            self.usage[key_hash] = {
                'last_reset': today,
                'requests_count': 0,
                'last_error': None,
                'is_exhausted': False
            }
            logger.info(f"[REFRESH] Reset exhaustion status for key {key_hash}")
    
    def get_available_key(self, estimated_cost: int = 1, operation: str = 'default') -> str:
        """
        Get an available API key with sufficient quota.
        
        Args:
            estimated_cost: Estimated quota cost for the operation
            operation: Type of operation (for cost calculation)
            
        Returns:
            Available API key
            
        Raises:
            APIError: When all keys are exhausted
        """
        with self._lock:
            # Try each key starting from current index
            attempts = 0
            while attempts < len(self.api_keys):
                key = self.api_keys[self.current_index]
                key_hash = self._hash_key(key)
                
                # Reset if new day
                self._reset_if_new_day(key_hash)
                
                # Check if key is exhausted (no quota calculation)
                if not self.usage[key_hash]['is_exhausted']:
                    # Use this key
                    logger.info(f"[API] Using YouTube API key #{self.current_index + 1} (hash: {key_hash})")
                    return key
                
                # Try next key (this key is exhausted)
                old_index = self.current_index
                self.current_index = (self.current_index + 1) % len(self.api_keys)
                old_hash = self._hash_key(self.api_keys[old_index])
                new_hash = self._hash_key(self.api_keys[self.current_index])
                logger.info(f"[ROTATE] Switching from API key {old_hash} to {new_hash} (previous key exhausted)")
                attempts += 1
            
            # All keys exhausted
            exhausted_keys = len([k for k in self.usage.values() if k['is_exhausted']])
            
            raise APIError(
                api_name="YouTube",
                status_code=403,
                message=f"All {exhausted_keys}/{len(self.api_keys)} API keys exhausted for today"
            )
    
    def record_usage(self, api_key: str, actual_cost: int = 0, success: bool = True, error: str = None) -> None:
        """
        Record API usage result (simplified - no cost tracking).
        
        Args:
            api_key: The API key that was used
            actual_cost: Ignored (kept for backward compatibility)
            success: Whether the request succeeded
            error: Error message if failed
        """
        with self._lock:
            key_hash = self._hash_key(api_key)
            
            if key_hash in self.usage:
                self.usage[key_hash]['requests_count'] += 1
                
                if not success:
                    self.usage[key_hash]['last_error'] = error
                    
                    # Mark as exhausted if quota error (403 or quotaExceeded)
                    if error and ('403' in str(error) or 'quotaExceeded' in str(error)):
                        self.usage[key_hash]['is_exhausted'] = True
                        logger.warning(f"[EXHAUST] Key #{self.current_index + 1} (hash: {key_hash}) marked as exhausted due to quota limit")
                
                # Move to next key for round-robin
                self.current_index = (self.current_index + 1) % len(self.api_keys)
    
    def get_quota_summary(self) -> Dict:
        """
        Get current API key status summary.
        
        Returns:
            Dictionary with key status information
        """
        with self._lock:
            summary = {
                'keys': [],
                'total_keys': len(self.api_keys),
                'available_keys': 0,
                'exhausted_keys': 0,
                'strategy': 'reactive_round_robin'
            }
            
            for i, key in enumerate(self.api_keys):
                key_hash = self._hash_key(key)
                self._reset_if_new_day(key_hash)
                
                is_exhausted = self.usage[key_hash]['is_exhausted']
                if not is_exhausted:
                    summary['available_keys'] += 1
                else:
                    summary['exhausted_keys'] += 1
                
                summary['keys'].append({
                    'index': i + 1,
                    'hash': key_hash,
                    'status': 'exhausted' if is_exhausted else 'available',
                    'requests': self.usage[key_hash]['requests_count'],
                    'is_exhausted': is_exhausted,
                    'last_error': self.usage[key_hash]['last_error']
                })
            
            summary['next_reset'] = (datetime.now().date() + timedelta(days=1)).isoformat()
            
            return summary
    
    def get_available_key_count(self) -> int:
        """
        Get count of available (non-exhausted) keys.
        
        Returns:
            Number of available keys
        """
        return len([
            key for key in self.api_keys
            if not self.usage[self._hash_key(key)]['is_exhausted']
        ])
    
    def force_reset(self) -> None:
        """Force reset all exhaustion status (useful for testing)"""
        with self._lock:
            for key_hash in self.usage:
                self.usage[key_hash] = {
                    'last_reset': datetime.now().date(),
                    'requests_count': 0,
                    'last_error': None,
                    'is_exhausted': False
                }
            logger.info("[REFRESH] Force reset all API key exhaustion status")