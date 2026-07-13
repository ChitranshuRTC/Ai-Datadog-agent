"""Integration tests for system endpoints."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_expected_payload() -> None:
    """Health endpoint exposes the required service metadata."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "aiops-platform",
        "version": "1.0.0",
    }


def test_version_returns_expected_payload() -> None:
    """Version endpoint exposes the service metadata."""
    with TestClient(app) as client:
        response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"service": "aiops-platform", "version": "1.0.0"}
