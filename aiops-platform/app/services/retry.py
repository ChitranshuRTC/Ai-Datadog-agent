"""Reusable asynchronous retry policy for transient integration failures."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

T = TypeVar("T")


class AsyncRetryPolicy:
    """Retries transient HTTP and transport failures using capped exponential backoff."""

    def __init__(self, max_attempts: int, base_delay_seconds: float) -> None:
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds

    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Execute an operation, retrying only transient HTTP failures."""
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await operation()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {429, 500, 502, 503, 504}
                if not retryable or attempt == self._max_attempts:
                    raise
                await asyncio.sleep(min(30.0, self._base_delay_seconds * (2 ** (attempt - 1))) + random.uniform(0, 0.25))
        raise RuntimeError("Retry policy exhausted unexpectedly.")
