"""Concurrency-safe storage for incident-to-Slack-thread mappings."""

import asyncio
from collections.abc import Awaitable, Callable


class InMemoryThreadStore:
    """Process-local thread mapping that deduplicates concurrent webhook delivery."""

    def __init__(self) -> None:
        self._threads: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get(self, incident_id: str) -> str | None:
        """Retrieve an existing Slack thread timestamp."""
        async with self._lock:
            return self._threads.get(incident_id)

    async def save(self, incident_id: str, thread_id: str) -> None:
        """Persist a Slack thread timestamp for the incident lifecycle."""
        async with self._lock:
            self._threads[incident_id] = thread_id

    async def get_or_create(self, incident_id: str, create: Callable[[], Awaitable[str]]) -> str:
        """Atomically retrieve an existing mapping or create and save a new mapping."""
        async with self._lock:
            if thread_id := self._threads.get(incident_id):
                return thread_id
            thread_id = await create()
            self._threads[incident_id] = thread_id
            return thread_id
