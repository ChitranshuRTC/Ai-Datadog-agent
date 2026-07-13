"""Incident application service coordinating Slack notification delivery."""

from app.models.incident import Incident
from app.services.slack_thread_manager import SlackThreadManager


class IncidentService:
    """Creates exactly one Slack incident thread per incident identifier per process."""

    def __init__(self, thread_manager: SlackThreadManager) -> None:
        self._thread_manager = thread_manager

    async def notify(self, incident: Incident) -> str:
        """Create and store a Slack thread, or return the existing thread ID."""
        return await self._thread_manager.get_or_create(incident)

    async def aclose(self) -> None:
        """Close resources owned by the incident service."""
        await self._thread_manager.aclose()
