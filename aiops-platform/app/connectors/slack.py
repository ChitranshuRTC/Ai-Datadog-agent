"""Async Slack Web API connector."""

import logging
from typing import Any

import httpx

from app.config.settings import Settings
from app.services.retry import AsyncRetryPolicy

logger = logging.getLogger(__name__)


class SlackDeliveryError(RuntimeError):
    """Raised when Slack does not accept an incident notification."""


class SlackConnector:
    """Posts messages to Slack using a bot token and the Web API."""

    def __init__(self, bot_token: str | None, channel: str | None, api_base_url: str, retry_policy: AsyncRetryPolicy) -> None:
        self._bot_token = bot_token
        self._channel = channel
        self._client = httpx.AsyncClient(base_url=api_base_url, timeout=httpx.Timeout(10.0))
        self._retry_policy = retry_policy

    @classmethod
    def from_settings(cls, settings: Settings) -> "SlackConnector":
        """Build a connector using validated service configuration."""
        return cls(
            bot_token=settings.slack_bot_token.get_secret_value() if settings.slack_bot_token else None,
            channel=settings.slack_incident_channel,
            api_base_url=str(settings.slack_api_base_url),
            retry_policy=AsyncRetryPolicy(settings.integration_max_retries, settings.integration_retry_base_delay_seconds),
        )

    async def create_thread(self, blocks: list[dict[str, Any]]) -> str:
        """Publish the parent message of an incident Slack thread and return its timestamp."""
        if not self._bot_token or not self._channel:
            raise SlackDeliveryError("Slack integration is not configured.")

        async def post() -> str:
            response = await self._client.post(
                "chat.postMessage",
                headers={"Authorization": f"Bearer {self._bot_token}"},
                json={"channel": self._channel, "blocks": blocks, "text": "Incident detected"},
            )
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise SlackDeliveryError("Slack returned a non-JSON response.") from exc
            if response.is_error or not payload.get("ok") or not isinstance(payload.get("ts"), str):
                raise SlackDeliveryError(f"Slack rejected message: {payload.get('error', response.text)}")
            return payload["ts"]

        try:
            return await self._retry_policy.execute(post)
        except (httpx.HTTPError, SlackDeliveryError) as exc:
            logger.exception("Slack incident delivery failed")
            raise SlackDeliveryError("Unable to create Slack incident thread.") from exc

    async def post_thread_update(self, thread_id: str, text: str) -> None:
        """Post a remediation status update in an existing incident thread."""
        if not self._bot_token or not self._channel:
            raise SlackDeliveryError("Slack integration is not configured.")

        async def post() -> None:
            response = await self._client.post(
                "chat.postMessage",
                headers={"Authorization": f"Bearer {self._bot_token}"},
                json={"channel": self._channel, "thread_ts": thread_id, "text": text},
            )
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            payload = response.json()
            if response.is_error or not payload.get("ok"):
                raise SlackDeliveryError(f"Slack rejected thread update: {payload.get('error', response.text)}")

        try:
            await self._retry_policy.execute(post)
        except (httpx.HTTPError, SlackDeliveryError) as exc:
            logger.exception("Slack thread update failed")
            raise SlackDeliveryError("Unable to update Slack incident thread.") from exc

    async def aclose(self) -> None:
        """Release pooled HTTP resources."""
        await self._client.aclose()
