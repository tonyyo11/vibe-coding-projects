"""
Shared utility functions for Jamf Health Tool.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Pattern, Set, Tuple


def parse_line_delimited_file(path: str) -> List[str]:
    """
    Parse a file containing one item per line, stripping whitespace and ignoring empty lines.

    Args:
        path: Path to the file to parse

    Returns:
        List of non-empty strings from the file
    """
    tokens: List[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        val = line.strip()
        if val:
            tokens.append(val)
    return tokens


def split_computer_identifiers(inputs: Iterable[str]) -> Tuple[Set[int], Set[str], Set[str]]:
    """
    Split a list of computer identifiers into IDs, serials, and names.

    Args:
        inputs: Iterable of strings that could be IDs, serial numbers, or hostnames

    Returns:
        Tuple of (ids, serials, names) where:
        - ids: Set of integer computer IDs
        - serials: Set of uppercase serial numbers (8+ alphanumeric chars)
        - names: Set of computer hostnames

    Examples:
        >>> split_computer_identifiers(["123", "ABC12345678", "mac-laptop"])
        ({123}, {'ABC12345678'}, {'mac-laptop'})
    """
    ids: Set[int] = set()
    serials: Set[str] = set()
    names: Set[str] = set()

    for item in inputs:
        item = item.strip()
        if not item:
            continue

        # Try to parse as integer ID
        if item.isdigit():
            ids.add(int(item))
        # Check if it looks like a serial number (8+ alphanumeric chars)
        elif re.fullmatch(r"[A-Za-z0-9]{8,}", item):
            serials.add(item.upper())
        # Otherwise treat as hostname/name
        else:
            names.add(item)

    return ids, serials, names


def validate_policy_ids(policy_ids: Iterable[int]) -> List[int]:
    """
    Validate and deduplicate policy IDs.

    Args:
        policy_ids: Iterable of policy IDs to validate

    Returns:
        Deduplicated list of valid policy IDs

    Raises:
        ValueError: If any policy ID is invalid (non-positive)
    """
    validated = []
    seen = set()

    for pid in policy_ids:
        if pid <= 0:
            raise ValueError(f"Invalid policy ID: {pid}. Policy IDs must be positive integers.")
        if pid not in seen:
            validated.append(pid)
            seen.add(pid)

    return validated


def format_size_bytes(size_bytes: int) -> str:
    """
    Format a byte count as a human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string like "1.5 MB"
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def parse_jamf_datetime(date_str: str) -> Optional[datetime]:
    """
    Parse datetime strings from Jamf API which can be in multiple formats.

    Jamf returns dates in various formats:
    - ISO8601: "2025-03-15T05:49:00Z" or "2025-03-15T05:49:00+00:00"
    - US format: "03/15/2025 05:49 AM"
    - Epoch timestamps: "1710486540000" (milliseconds since epoch)

    Args:
        date_str: Date string from Jamf API

    Returns:
        datetime object with UTC timezone, or None if parsing fails

    Examples:
        >>> parse_jamf_datetime("03/15/2025 05:49 AM")
        datetime(2025, 3, 15, 5, 49, tzinfo=timezone.utc)
        >>> parse_jamf_datetime("2025-03-15T05:49:00Z")
        datetime(2025, 3, 15, 5, 49, tzinfo=timezone.utc)
    """
    if not date_str:
        return None

    # Try ISO8601 format first
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        pass

    # Try US format: "03/15/2025 05:49 AM" or "03/15/2025 05:49:00 AM"
    try:
        # Try with seconds
        dt = datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    try:
        # Try without seconds
        dt = datetime.strptime(date_str, "%m/%d/%Y %I:%M %p")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    # Try epoch timestamp (milliseconds)
    try:
        timestamp_ms = int(date_str)
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except (ValueError, OSError):
        pass

    # If all else fails, return None
    return None


def parse_flexible_date(date_string: str, end_of_day: bool = False) -> str:
    """
    Convert various user-provided date formats to ISO8601 UTC format.

    Accepts:
        - ISO8601: "2024-11-22T00:00:00Z" (returned as-is)
        - ISO8601 without timezone: "2024-11-22T00:00:00" (adds Z)
        - Simple date formats:
          - "2024-11-22" (ISO standard with dash)
          - "11-22-2024" (US style with dash)
          - "11/22/2024" (US style with slash)
          - "2024/11/22" (ISO with slash)
          - "22.11.2024" (European style)
          - "22-11-2024" (European style with dash)

    Args:
        date_string: Date string in various formats
        end_of_day: If True, time defaults to 23:59:59 instead of 00:00:00

    Returns:
        ISO8601 string (YYYY-MM-DDTHH:MM:SSZ)

    Raises:
        ValueError: If date format cannot be parsed

    Examples:
        >>> parse_flexible_date("2024-11-22")
        '2024-11-22T00:00:00Z'

        >>> parse_flexible_date("11-22-2024")
        '2024-11-22T00:00:00Z'

        >>> parse_flexible_date("2024-11-22", end_of_day=True)
        '2024-11-22T23:59:59Z'

        >>> parse_flexible_date("2024-11-22T00:00:00Z")
        '2024-11-22T00:00:00Z'

        >>> parse_flexible_date("11/22/2024")
        '2024-11-22T00:00:00Z'
    """
    # Already ISO8601 with Z - return as-is
    if 'T' in date_string and date_string.endswith('Z'):
        return date_string

    # ISO8601 without Z - add it
    if 'T' in date_string and not date_string.endswith('Z'):
        return f"{date_string}Z"

    # Default time based on parameter
    default_time = "23:59:59" if end_of_day else "00:00:00"

    # Try various date-only formats
    formats = [
        "%Y-%m-%d",      # 2024-11-22 (ISO standard)
        "%m-%d-%Y",      # 11-22-2024 (US style with dash)
        "%Y/%m/%d",      # 2024/11/22 (ISO with slash)
        "%m/%d/%Y",      # 11/22/2024 (US style with slash)
        "%d.%m.%Y",      # 22.11.2024 (European style)
        "%d-%m-%Y",      # 22-11-2024 (European style with dash)
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_string, fmt)
            return dt.strftime(f"%Y-%m-%dT{default_time}Z")
        except ValueError:
            continue

    # No format matched
    raise ValueError(
        f"Invalid date format: '{date_string}'. "
        f"Supported formats:\n"
        f"  - ISO8601: 2024-11-22T00:00:00Z\n"
        f"  - Simple date: 2024-11-22, 11-22-2024, 11/22/2024"
    )


def validate_date_range(start: str, end: str) -> tuple[str, str]:
    """
    Validate and parse a date range.

    Args:
        start: Start date in flexible format
        end: End date in flexible format

    Returns:
        Tuple of (start_iso8601, end_iso8601)

    Raises:
        ValueError: If dates are invalid or end is before start

    Examples:
        >>> validate_date_range("2024-11-18", "2024-11-22")
        ('2024-11-18T00:00:00Z', '2024-11-22T23:59:59Z')

        >>> validate_date_range("11-18-2024", "11/22/2024")
        ('2024-11-18T00:00:00Z', '2024-11-22T23:59:59Z')
    """
    start_parsed = parse_flexible_date(start, end_of_day=False)
    end_parsed = parse_flexible_date(end, end_of_day=True)

    # Validate end is after start
    start_dt = datetime.fromisoformat(start_parsed.rstrip('Z'))
    end_dt = datetime.fromisoformat(end_parsed.rstrip('Z'))

    if end_dt < start_dt:
        raise ValueError(
            f"End date ({end}) must be after start date ({start})"
        )

    return start_parsed, end_parsed


def compile_safe_regex(pattern: str, flags: int = 0) -> Pattern[str]:
    """
    Safely compile a regex pattern with validation and error handling.

    Args:
        pattern: Regular expression pattern string
        flags: Optional regex flags (e.g., re.IGNORECASE)

    Returns:
        Compiled regex pattern

    Raises:
        ValueError: If pattern is invalid or potentially dangerous

    Examples:
        >>> compile_safe_regex("test.*")
        re.compile('test.*')

        >>> compile_safe_regex("test", re.IGNORECASE)
        re.compile('test', re.IGNORECASE)

        >>> compile_safe_regex("((((")  # doctest: +SKIP
        ValueError: Invalid regex pattern: unbalanced parenthesis
    """
    if not pattern:
        raise ValueError("Regex pattern cannot be empty")

    # Check for potentially problematic patterns that could cause ReDoS
    # Warn about nested quantifiers like (a+)+ or (a*)*
    nested_quantifiers = re.search(r'\([^)]*[*+]\)[*+?{]', pattern)
    if nested_quantifiers:
        raise ValueError(
            f"Potentially dangerous regex pattern detected: nested quantifiers can cause performance issues. "
            f"Pattern: '{pattern}'"
        )

    # Try to compile the regex
    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}") from e

    return compiled


def validate_profile_ids(profile_ids: Iterable[int]) -> List[int]:
    """
    Validate and deduplicate profile IDs.

    Args:
        profile_ids: Iterable of profile IDs to validate

    Returns:
        Deduplicated list of valid profile IDs

    Raises:
        ValueError: If any profile ID is invalid (non-positive)

    Examples:
        >>> validate_profile_ids([1, 2, 3, 2, 1])
        [1, 2, 3]

        >>> validate_profile_ids([5, -1, 10])  # doctest: +SKIP
        ValueError: Invalid profile ID: -1. Profile IDs must be positive integers.
    """
    validated = []
    seen = set()

    for pid in profile_ids:
        if pid <= 0:
            raise ValueError(f"Invalid profile ID: {pid}. Profile IDs must be positive integers.")
        if pid not in seen:
            validated.append(pid)
            seen.add(pid)

    return validated
