"""
Concurrency utilities for parallel API calls.

Provides thread-based concurrency for I/O-bound operations like API calls.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable, List, Optional, TypeVar

T = TypeVar("T")


def execute_concurrent(
    func: Callable[[Any], T],
    items: Iterable[Any],
    max_workers: int = 10,
    logger: Optional[logging.Logger] = None,
    description: str = "Processing items",
) -> List[T]:
    """
    Execute a function concurrently across multiple items using threads.

    Suitable for I/O-bound operations like API calls where the GIL is released.

    Args:
        func: Function to execute for each item (should accept single argument)
        items: Iterable of items to process
        max_workers: Maximum number of concurrent threads (default: 10)
        logger: Optional logger for progress updates
        description: Description for logging

    Returns:
        List of results in the same order as items

    Raises:
        Exception: If any item processing fails, the first exception is re-raised

    Examples:
        >>> def fetch_computer(comp_id):
        ...     return client.get_computer(comp_id)
        >>> computer_ids = [1, 2, 3, 4, 5]
        >>> computers = execute_concurrent(fetch_computer, computer_ids, max_workers=5)

        >>> def get_apps(computer):
        ...     return client.get_computer_applications(computer.id)
        >>> apps = execute_concurrent(get_apps, computers, max_workers=10, description="Fetching applications")
    """
    log = logger or logging.getLogger(__name__)
    items_list = list(items)
    total = len(items_list)

    if total == 0:
        return []

    if total == 1:
        # No need for concurrency with single item
        return [func(items_list[0])]

    log.debug(f"{description}: processing {total} items with {max_workers} workers")

    results: List[Optional[T]] = [None] * total
    item_to_index = {id(item): idx for idx, item in enumerate(items_list)}
    errors = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_item = {executor.submit(func, item): item for item in items_list}

        # Collect results as they complete
        completed = 0
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            idx = item_to_index[id(item)]

            try:
                result = future.result()
                results[idx] = result
                completed += 1

                # Log progress every 10% or every 10 items
                if total >= 20 and completed % max(1, total // 10) == 0:
                    log.debug(f"{description}: {completed}/{total} completed ({completed/total*100:.0f}%)")
                elif completed % 10 == 0:
                    log.debug(f"{description}: {completed}/{total} completed")

            except Exception as exc:
                log.error(f"{description}: Error processing item at index {idx}: {exc}")
                errors.append((idx, exc))

    log.debug(f"{description}: completed {completed}/{total} items")

    # If there were errors, raise the first one
    if errors:
        idx, exc = errors[0]
        log.error(f"{description}: Failed with {len(errors)} errors, first error at index {idx}")
        raise exc

    # Type check - all results should be filled
    return [r for r in results if r is not None]  # type: ignore


def execute_concurrent_with_fallback(
    func: Callable[[Any], T],
    items: Iterable[Any],
    max_workers: int = 10,
    logger: Optional[logging.Logger] = None,
    description: str = "Processing items",
    skip_errors: bool = True,
) -> List[T]:
    """
    Execute a function concurrently with error fallback (skip failed items).

    Similar to execute_concurrent but continues processing even if some items fail.
    Failed items are logged and skipped from results.

    Args:
        func: Function to execute for each item
        items: Iterable of items to process
        max_workers: Maximum number of concurrent threads
        logger: Optional logger
        description: Description for logging
        skip_errors: If True, skip failed items; if False, raise on first error

    Returns:
        List of successful results (may be shorter than input if errors occurred)

    Examples:
        >>> def fetch_apps(comp_id):
        ...     # Some computers might not exist
        ...     return client.get_computer_applications(comp_id)
        >>> apps = execute_concurrent_with_fallback(
        ...     fetch_apps, computer_ids, skip_errors=True, description="Fetching apps"
        ... )
    """
    log = logger or logging.getLogger(__name__)
    items_list = list(items)
    total = len(items_list)

    if total == 0:
        return []

    if total == 1:
        try:
            return [func(items_list[0])]
        except Exception as exc:
            if skip_errors:
                log.warning(f"{description}: Skipped failed item: {exc}")
                return []
            else:
                raise

    log.debug(f"{description}: processing {total} items with {max_workers} workers (skip_errors={skip_errors})")

    results: List[T] = []
    errors = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(func, item): item for item in items_list}

        completed = 0
        for future in as_completed(future_to_item):
            try:
                result = future.result()
                results.append(result)
                completed += 1

                # Log progress
                if total >= 20 and completed % max(1, total // 10) == 0:
                    log.debug(f"{description}: {completed}/{total} completed ({completed/total*100:.0f}%)")

            except Exception as exc:
                errors += 1
                if skip_errors:
                    log.warning(f"{description}: Skipped failed item (error {errors}): {exc}")
                else:
                    log.error(f"{description}: Failed processing item: {exc}")
                    raise

    log.debug(f"{description}: completed {len(results)}/{total} items ({errors} errors)")

    return results


class RateLimiter:
    """
    Simple rate limiter for API calls to avoid overwhelming the server.

    Uses token bucket algorithm with thread-safe access.
    """

    def __init__(self, max_requests_per_second: float = 10.0):
        """
        Initialize rate limiter.

        Args:
            max_requests_per_second: Maximum requests allowed per second

        Examples:
            >>> limiter = RateLimiter(max_requests_per_second=5.0)
            >>> with limiter:
            ...     # Make API call
            ...     result = client.get_computer(123)
        """
        import threading
        import time

        self.max_rate = max_requests_per_second
        self.min_interval = 1.0 / max_requests_per_second if max_requests_per_second > 0 else 0
        self.last_call = 0.0
        self.lock = threading.Lock()
        self.time = time

    def __enter__(self):
        """Acquire rate limit before API call."""
        with self.lock:
            now = self.time.time()
            time_since_last = now - self.last_call

            if time_since_last < self.min_interval:
                # Need to wait
                sleep_time = self.min_interval - time_since_last
                self.time.sleep(sleep_time)

            self.last_call = self.time.time()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release after API call."""
        pass
