"""
Local file-based caching for Jamf API responses.

Provides persistent caching to reduce redundant API calls and improve performance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class FileCache:
    """
    Simple file-based cache with TTL support.

    Cache entries are stored as JSON files in a cache directory.
    Each entry includes metadata (timestamp, TTL) and the cached data.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        default_ttl: int = 3600,
        enabled: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the file cache.

        Args:
            cache_dir: Directory to store cache files (default: ~/.jamf_health_tool/cache)
            default_ttl: Default time-to-live in seconds (default: 3600 = 1 hour)
            enabled: Whether caching is enabled (default: True)
            logger: Optional logger instance

        Examples:
            >>> cache = FileCache()
            >>> cache.set("my_key", {"data": "value"})
            >>> cache.get("my_key")
            {'data': 'value'}
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".jamf_health_tool" / "cache"

        self.cache_dir = cache_dir
        self.default_ttl = default_ttl
        self.enabled = enabled
        self.logger = logger or logging.getLogger(__name__)

        # Create cache directory if it doesn't exist
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Cache directory: {self.cache_dir}")

    def _make_cache_key(self, key: str) -> str:
        """
        Generate a safe filesystem cache key from an arbitrary string.

        Uses SHA256 hash to ensure key is filesystem-safe and consistent length.

        Args:
            key: Original cache key

        Returns:
            Filesystem-safe cache key

        Examples:
            >>> cache = FileCache(enabled=False)
            >>> cache._make_cache_key("test_key")
            '9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa'
        """
        return hashlib.sha256(key.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get the file path for a cache key."""
        return self.cache_dir / f"{cache_key}.json"

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a value from the cache if it exists and is not expired.

        Args:
            key: Cache key

        Returns:
            Cached value if found and not expired, None otherwise

        Examples:
            >>> cache = FileCache()
            >>> cache.set("test", {"value": 123})
            >>> cache.get("test")
            {'value': 123}
            >>> cache.get("nonexistent")
            None
        """
        if not self.enabled:
            return None

        cache_key = self._make_cache_key(key)
        cache_path = self._get_cache_path(cache_key)

        if not cache_path.exists():
            self.logger.debug(f"Cache miss: {key}")
            return None

        try:
            with cache_path.open("r", encoding="utf-8") as f:
                entry = json.load(f)

            # Check if entry has expired
            cached_at = entry.get("cached_at", 0)
            ttl = entry.get("ttl", self.default_ttl)
            age = time.time() - cached_at

            if age > ttl:
                self.logger.debug(f"Cache expired: {key} (age: {age:.1f}s, ttl: {ttl}s)")
                # Remove expired entry
                cache_path.unlink(missing_ok=True)
                return None

            self.logger.debug(f"Cache hit: {key} (age: {age:.1f}s)")
            return entry.get("data")

        except (json.JSONDecodeError, KeyError) as e:
            self.logger.warning(f"Invalid cache entry for {key}: {e}")
            # Remove corrupted entry
            cache_path.unlink(missing_ok=True)
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Store a value in the cache with optional TTL.

        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
            ttl: Time-to-live in seconds (default: use default_ttl)

        Examples:
            >>> cache = FileCache()
            >>> cache.set("test", {"data": "value"})
            >>> cache.set("short_lived", {"data": "value"}, ttl=60)
        """
        if not self.enabled:
            return

        cache_key = self._make_cache_key(key)
        cache_path = self._get_cache_path(cache_key)

        entry = {
            "key": key,  # Store original key for debugging
            "cached_at": time.time(),
            "ttl": ttl or self.default_ttl,
            "data": value,
        }

        try:
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2)
            self.logger.debug(f"Cache stored: {key}")
        except (TypeError, OSError) as e:
            self.logger.warning(f"Failed to cache {key}: {e}")

    def delete(self, key: str) -> bool:
        """
        Delete a specific cache entry.

        Args:
            key: Cache key to delete

        Returns:
            True if entry was deleted, False if it didn't exist

        Examples:
            >>> cache = FileCache()
            >>> cache.set("test", "value")
            >>> cache.delete("test")
            True
            >>> cache.delete("test")
            False
        """
        if not self.enabled:
            return False

        cache_key = self._make_cache_key(key)
        cache_path = self._get_cache_path(cache_key)

        if cache_path.exists():
            cache_path.unlink()
            self.logger.debug(f"Cache deleted: {key}")
            return True

        return False

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of cache entries deleted

        Examples:
            >>> cache = FileCache()
            >>> cache.set("key1", "value1")
            >>> cache.set("key2", "value2")
            >>> cache.clear()
            2
        """
        if not self.enabled:
            return 0

        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError as e:
                self.logger.warning(f"Failed to delete {cache_file}: {e}")

        self.logger.info(f"Cleared {count} cache entries")
        return count

    def stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics

        Examples:
            >>> cache = FileCache()
            >>> cache.set("test", "value")
            >>> stats = cache.stats()
            >>> stats['total_entries']
            1
        """
        if not self.enabled:
            return {
                "enabled": False,
                "cache_dir": str(self.cache_dir),
                "total_entries": 0,
                "total_size_bytes": 0,
            }

        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)

        # Count expired vs valid entries
        valid_entries = 0
        expired_entries = 0
        current_time = time.time()

        for cache_file in cache_files:
            try:
                with cache_file.open("r", encoding="utf-8") as f:
                    entry = json.load(f)
                cached_at = entry.get("cached_at", 0)
                ttl = entry.get("ttl", self.default_ttl)
                if (current_time - cached_at) <= ttl:
                    valid_entries += 1
                else:
                    expired_entries += 1
            except (json.JSONDecodeError, KeyError):
                expired_entries += 1

        return {
            "enabled": True,
            "cache_dir": str(self.cache_dir),
            "default_ttl": self.default_ttl,
            "total_entries": len(cache_files),
            "valid_entries": valid_entries,
            "expired_entries": expired_entries,
            "total_size_bytes": total_size,
        }


def make_cache_key(tenant_url: str, endpoint: str, **params) -> str:
    """
    Generate a cache key for API requests.

    Args:
        tenant_url: Jamf tenant URL
        endpoint: API endpoint path
        **params: Query parameters or request-specific identifiers

    Returns:
        Cache key string

    Examples:
        >>> make_cache_key("https://tenant.jamfcloud.com", "/computers", computer_id=123)
        'https://tenant.jamfcloud.com|/computers|computer_id=123'

        >>> make_cache_key("https://tenant.jamfcloud.com", "/policies")
        'https://tenant.jamfcloud.com|/policies'
    """
    # Sort params for consistent key generation
    param_str = "|".join(f"{k}={v}" for k, v in sorted(params.items()))
    parts = [tenant_url, endpoint]
    if param_str:
        parts.append(param_str)
    return "|".join(parts)
