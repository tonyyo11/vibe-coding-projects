"""
Tests for new features in version 2.0
"""

import pytest
import re
import tempfile
import time
from pathlib import Path
from datetime import datetime

# Import the new utility functions
from jamf_health_tool.utils import (
    parse_flexible_date,
    validate_date_range,
    compile_safe_regex,
    validate_profile_ids,
)
from jamf_health_tool.cache import FileCache, make_cache_key
from jamf_health_tool.concurrency import execute_concurrent, execute_concurrent_with_fallback


class TestFlexibleDateParsing:
    """Test flexible date input parsing"""

    def test_iso_date_format(self):
        """Test ISO date format (YYYY-MM-DD)"""
        result = parse_flexible_date("2024-11-22", end_of_day=False)
        assert result == "2024-11-22T00:00:00Z"

    def test_us_dash_format(self):
        """Test US format with dashes (MM-DD-YYYY)"""
        result = parse_flexible_date("11-22-2024", end_of_day=False)
        assert result == "2024-11-22T00:00:00Z"

    def test_us_slash_format(self):
        """Test US format with slashes (MM/DD/YYYY)"""
        result = parse_flexible_date("11/22/2024", end_of_day=False)
        assert result == "2024-11-22T00:00:00Z"

    def test_european_format(self):
        """Test European format (DD.MM.YYYY)"""
        result = parse_flexible_date("22.11.2024", end_of_day=False)
        assert result == "2024-11-22T00:00:00Z"

    def test_end_of_day_flag(self):
        """Test end_of_day flag"""
        result_start = parse_flexible_date("11-22-2024", end_of_day=False)
        result_end = parse_flexible_date("11-22-2024", end_of_day=True)

        assert result_start == "2024-11-22T00:00:00Z"
        assert result_end == "2024-11-22T23:59:59Z"

    def test_iso8601_with_z(self):
        """Test ISO8601 with Z is returned as-is"""
        input_date = "2024-11-22T12:00:00Z"
        result = parse_flexible_date(input_date)
        assert result == input_date

    def test_invalid_date_format(self):
        """Test invalid date format raises ValueError"""
        with pytest.raises(ValueError):
            parse_flexible_date("invalid-date")


class TestDateRangeValidation:
    """Test date range validation"""

    def test_valid_range(self):
        """Test valid date range"""
        start, end = validate_date_range("11-18-2024", "11-22-2024")
        assert start == "2024-11-18T00:00:00Z"
        assert end == "2024-11-22T23:59:59Z"

    def test_mixed_formats(self):
        """Test mixed date formats"""
        start, end = validate_date_range("2024-11-18", "11/22/2024")
        assert start == "2024-11-18T00:00:00Z"
        assert end == "2024-11-22T23:59:59Z"

    def test_end_before_start(self):
        """Test end date before start date raises ValueError"""
        with pytest.raises(ValueError, match="End date.*must be after start date"):
            validate_date_range("11-22-2024", "11-18-2024")


class TestSafeRegex:
    """Test safe regex compilation"""

    def test_valid_regex(self):
        """Test valid regex pattern"""
        pattern = compile_safe_regex("test.*", re.IGNORECASE)
        assert pattern.search("testing") is not None

    def test_empty_pattern(self):
        """Test empty pattern raises ValueError"""
        with pytest.raises(ValueError, match="cannot be empty"):
            compile_safe_regex("")

    def test_nested_quantifiers(self):
        """Test dangerous nested quantifiers are rejected"""
        with pytest.raises(ValueError, match="dangerous"):
            compile_safe_regex("(a+)+")

    def test_invalid_regex(self):
        """Test invalid regex raises ValueError"""
        with pytest.raises(ValueError, match="Invalid regex"):
            compile_safe_regex("((((")  # Unbalanced parentheses


class TestProfileIDValidation:
    """Test profile ID validation"""

    def test_valid_ids(self):
        """Test valid profile IDs"""
        result = validate_profile_ids([1, 2, 3])
        assert result == [1, 2, 3]

    def test_deduplication(self):
        """Test duplicate IDs are removed"""
        result = validate_profile_ids([1, 2, 3, 2, 1])
        assert result == [1, 2, 3]

    def test_invalid_id(self):
        """Test invalid (non-positive) ID raises ValueError"""
        with pytest.raises(ValueError, match="must be positive"):
            validate_profile_ids([1, 2, -1])

    def test_zero_id(self):
        """Test zero ID raises ValueError"""
        with pytest.raises(ValueError, match="must be positive"):
            validate_profile_ids([0])


class TestCaching:
    """Test file-based caching"""

    def test_cache_set_and_get(self):
        """Test basic cache set and get"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=Path(tmpdir), default_ttl=60)
            cache.set("test_key", {"data": "value"})
            result = cache.get("test_key")
            assert result == {"data": "value"}

    def test_cache_expiration(self):
        """Test cache entry expires after TTL"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=Path(tmpdir), default_ttl=1)  # 1 second TTL
            cache.set("test_key", {"data": "value"})

            # Immediate retrieval should work
            result = cache.get("test_key")
            assert result == {"data": "value"}

            # Wait for expiration
            time.sleep(2)

            # Should return None after expiration
            result = cache.get("test_key")
            assert result is None

    def test_cache_miss(self):
        """Test cache miss returns None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=Path(tmpdir))
            result = cache.get("nonexistent_key")
            assert result is None

    def test_cache_delete(self):
        """Test cache entry deletion"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=Path(tmpdir))
            cache.set("test_key", {"data": "value"})
            assert cache.get("test_key") is not None

            cache.delete("test_key")
            assert cache.get("test_key") is None

    def test_cache_clear(self):
        """Test clearing all cache entries"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=Path(tmpdir))
            cache.set("key1", "value1")
            cache.set("key2", "value2")
            cache.set("key3", "value3")

            count = cache.clear()
            assert count == 3
            assert cache.get("key1") is None
            assert cache.get("key2") is None

    def test_cache_stats(self):
        """Test cache statistics"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = FileCache(cache_dir=Path(tmpdir), default_ttl=60)
            cache.set("key1", "value1")
            cache.set("key2", "value2")

            stats = cache.stats()
            assert stats["enabled"] is True
            assert stats["total_entries"] == 2
            assert stats["valid_entries"] == 2
            assert stats["expired_entries"] == 0

    def test_cache_disabled(self):
        """Test cache behavior when disabled"""
        cache = FileCache(enabled=False)
        cache.set("test_key", "value")
        result = cache.get("test_key")
        assert result is None  # Should always return None when disabled

    def test_make_cache_key(self):
        """Test cache key generation"""
        key1 = make_cache_key("https://test.com", "/api/endpoint", param1="value1")
        key2 = make_cache_key("https://test.com", "/api/endpoint", param1="value1")
        key3 = make_cache_key("https://test.com", "/api/endpoint", param1="value2")

        # Same parameters should generate same key
        assert key1 == key2

        # Different parameters should generate different key
        assert key1 != key3


class TestConcurrency:
    """Test concurrent execution utilities"""

    def test_execute_concurrent(self):
        """Test basic concurrent execution"""
        def square(x):
            return x * x

        items = [1, 2, 3, 4, 5]
        results = execute_concurrent(square, items, max_workers=2)
        assert results == [1, 4, 9, 16, 25]

    def test_execute_concurrent_preserves_order(self):
        """Test that results preserve input order"""
        def slow_operation(x):
            time.sleep(0.01 if x == 1 else 0.001)  # First item slower
            return x * 2

        items = [1, 2, 3]
        results = execute_concurrent(slow_operation, items, max_workers=3)
        assert results == [2, 4, 6]  # Order preserved despite timing

    def test_execute_concurrent_single_item(self):
        """Test concurrent execution with single item (should not use threads)"""
        def identity(x):
            return x

        result = execute_concurrent(identity, [42], max_workers=5)
        assert result == [42]

    def test_execute_concurrent_with_fallback(self):
        """Test concurrent execution with error handling"""
        def may_fail(x):
            if x == 3:
                raise ValueError(f"Failed on {x}")
            return x * 2

        items = [1, 2, 3, 4]
        results = execute_concurrent_with_fallback(may_fail, items, skip_errors=True, max_workers=2)

        # Should get results for all items except the failing one
        assert len(results) == 3
        assert 2 in results
        assert 4 in results
        assert 8 in results

    def test_execute_concurrent_with_fallback_no_skip(self):
        """Test concurrent execution raises error when skip_errors=False"""
        def always_fails(x):
            raise ValueError("Intentional failure")

        items = [1, 2, 3]
        with pytest.raises(ValueError, match="Intentional failure"):
            execute_concurrent_with_fallback(always_fails, items, skip_errors=False, max_workers=2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
