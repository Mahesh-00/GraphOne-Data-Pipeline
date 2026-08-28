"""
Concurrency primitives shared by every scraper and the LLM orchestrator.

Design goal: scaling from 1k records to 500k records should only mean turning
up MAX_CONCURRENT_REQUESTS / adding more worker processes -- never touching
this logic.
"""
import asyncio
import random
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class RateLimiter:
    """Simple token-bucket limiter: caps requests/sec per source (politeness)."""

    def __init__(self, rate_per_sec: float):
        self.rate = rate_per_sec
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            min_interval = 1.0 / self.rate if self.rate > 0 else 0
            elapsed = now - self._last
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last = time.monotonic()


class RetryableError(Exception):
    """Raised by callers to signal 'retry me' (e.g. 429, 5xx, timeout)."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 5,
    base_backoff: float = 1.0,
    max_backoff: float = 60.0,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """
    Exponential backoff with full jitter, honoring an explicit retry_after
    (e.g. from a 429's Retry-After header) when the callee provides one.
    """
    attempt = 0
    while True:
        try:
            return await fn()
        except RetryableError as exc:
            attempt += 1
            if attempt > max_retries:
                raise
            if exc.retry_after is not None:
                delay = exc.retry_after
            else:
                capped = min(max_backoff, base_backoff * (2 ** (attempt - 1)))
                delay = random.uniform(0, capped)  # full jitter
            if on_retry:
                on_retry(attempt, exc)
            await asyncio.sleep(delay)


class ConcurrencyPool:
    """Wraps an asyncio.Semaphore so call sites read cleanly: `async with pool:`"""

    def __init__(self, max_concurrent: int):
        self._sem = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self):
        await self._sem.acquire()
        return self

    async def __aexit__(self, *exc):
        self._sem.release()
