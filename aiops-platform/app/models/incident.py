"""Domain model for incidents received from observability platforms."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class IncidentSeverity(StrEnum):
    """Normalized incident severities."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Incident:
    """Normalized alert details independent from the source platform."""

    identifier: str
    title: str
    severity: IncidentSeverity
    namespace: str
    service: str
    cluster: str
    occurred_at: datetime
    watchdog_summary: str
    pod_name: str | None = None
    event_type: str | None = None
    priority: str | None = None
    monitor_link: str | None = None
    snapshot: str | None = None
    alert_scope: str | None = None
    organization: str | None = None
    raw_payload: dict[str, Any] | None = None
    tags: dict[str, str] = field(default_factory=dict)
