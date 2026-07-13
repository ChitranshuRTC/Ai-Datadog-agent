"""Webhook endpoint tests without external Slack or Datadog access."""

from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.main import app


class FakeIncidentService:
    """Test double for Slack incident thread creation."""

    async def notify(self, incident) -> str:
        return f"thread-{incident.identifier}"

    async def aclose(self) -> None:
        return None


def test_datadog_webhook_is_authenticated_and_accepted(monkeypatch) -> None:
    monkeypatch.setenv("DATADOG_WEBHOOK_TOKEN", "test-token")
    get_settings.cache_clear()
    payload = {"id": "incident-1", "title": "OOMKilled", "alert_status": "Alert", "tags": ["namespace:payments", "service:api"]}
    with TestClient(app) as client:
        app.state.incident_service = FakeIncidentService()
        response = client.post("/webhooks/datadog", headers={"X-Datadog-Webhook-Token": "test-token"}, json=payload)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "incident_id": "incident-1", "slack_thread_id": "thread-incident-1"}
    assert response.headers["X-Request-ID"]
    get_settings.cache_clear()


def test_unknown_route_has_structured_not_found_error() -> None:
    with TestClient(app) as client:
        response = client.get("/not-a-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
