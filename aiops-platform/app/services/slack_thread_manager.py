"""Lifecycle manager for one Slack thread per incident."""

from app.connectors.slack import SlackConnector
from app.models.incident import Incident
from app.services.slack_blocks import build_incident_blocks
from app.services.thread_store import InMemoryThreadStore


class SlackThreadManager:
    """Creates or retrieves the Slack parent thread for an incident safely."""

    def __init__(self, slack_connector: SlackConnector, thread_store: InMemoryThreadStore) -> None:
        self._slack_connector = slack_connector
        self._thread_store = thread_store

    async def get_or_create(self, incident: Incident) -> str:
        """Return the stored thread ID or atomically create and persist a new one."""
        return await self._thread_store.get_or_create(
            incident.identifier,
            lambda: self._slack_connector.create_thread(build_incident_blocks(incident)),
        )

    async def aclose(self) -> None:
        """Close the connector owned by this manager."""
        await self._slack_connector.aclose()
