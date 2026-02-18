"""Retry decorator with exponential backoff.

Usage:
    from src.utils.retry import retry

    @retry(max_attempts=3, base_delay=1.0, exceptions=(ConnectionError, TimeoutError))
    def call_external_api():
        ...

    # Async version
    @retry(max_attempts=3, base_delay=1.0, exceptions=(ConnectionError,))
    async def call_external_api_async():
        ...
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from typing import Any, Callable, Sequence

from src.utils.logging import get_logger

logger = get_logger(__name__)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: Sequence[type[BaseException]] = (Exception,),
) -> Callable:
    """Retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay cap in seconds.
        backoff_factor: Multiplier for delay after each retry.
        jitter: Add random jitter to prevent thundering herd.
        exceptions: Tuple of exception types to catch and retry on.
    """
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                delay = base_delay
                last_exception: BaseException | None = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except tuple(exceptions) as e:
                        last_exception = e
                        if attempt == max_attempts:
                            logger.error(
                                f"{func.__name__} failed after {max_attempts} attempts: {e}"
                            )
                            raise
                        actual_delay = min(delay, max_delay)
                        if jitter:
                            actual_delay *= 0.5 + random.random()
                        logger.warning(
                            f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                            f"Retrying in {actual_delay:.1f}s..."
                        )
                        await asyncio.sleep(actual_delay)
                        delay *= backoff_factor
                raise last_exception  # type: ignore[misc]
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                delay = base_delay
                last_exception: BaseException | None = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        return func(*args, **kwargs)
                    except tuple(exceptions) as e:
                        last_exception = e
                        if attempt == max_attempts:
                            logger.error(
                                f"{func.__name__} failed after {max_attempts} attempts: {e}"
                            )
                            raise
                        actual_delay = min(delay, max_delay)
                        if jitter:
                            actual_delay *= 0.5 + random.random()
                        logger.warning(
                            f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                            f"Retrying in {actual_delay:.1f}s..."
                        )
                        time.sleep(actual_delay)
                        delay *= backoff_factor
                raise last_exception  # type: ignore[misc]
            return sync_wrapper
    return decorator
