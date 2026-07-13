"""Domain model for incidents received from observability platforms."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
