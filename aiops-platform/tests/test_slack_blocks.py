"""Tests for Slack Block Kit incident formatting."""

from datetime import UTC, datetime

from app.models.incident import Incident, IncidentSeverity
from app.services.slack_blocks import build_incident_blocks


def test_incident_blocks_include_required_details() -> None:
    blocks = build_incident_blocks(Incident("id", "Alert", IncidentSeverity.CRITICAL, "ns", "svc", "cluster", datetime.now(UTC), "Summary"))
    rendered = str(blocks)
    assert "🚨 Incident Detected" in rendered
    assert "Severity" in rendered
    assert "Watchdog Summary" in rendered
