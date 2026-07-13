"""Slack Block Kit formatting for incident notifications."""

from typing import Any

from app.models.incident import Incident


def build_incident_blocks(incident: Incident) -> list[dict[str, Any]]:
    """Create a compact, accessible Slack Block Kit incident message."""
    details = (
        f"*Severity:* {incident.severity.value}\n"
        f"*Namespace:* {incident.namespace}\n"
        f"*Service:* {incident.service}\n"
        f"*Cluster:* {incident.cluster}\n"
        f"*Time:* <!date^{int(incident.occurred_at.timestamp())}^{{date_short_pretty}} {{time}}|{incident.occurred_at.isoformat()}>"
    )
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🚨 Incident Detected", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{incident.title}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": details}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Watchdog Summary*\n{incident.watchdog_summary}"}},
    ]
