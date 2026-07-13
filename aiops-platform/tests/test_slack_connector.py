"""Tests for Slack API request and error handling."""

import httpx
import pytest

from app.connectors.slack import SlackConnector
from app.services.retry import AsyncRetryPolicy


@pytest.mark.asyncio
async def test_create_thread_returns_slack_timestamp() -> None:
    connector = SlackConnector("token", "C1", "https://slack.test/api/", AsyncRetryPolicy(1, 0.01))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True, "ts": "123.456"}))
    connector._client = httpx.AsyncClient(transport=transport, base_url="https://slack.test/api/")

    assert await connector.create_thread([]) == "123.456"
    await connector.aclose()
