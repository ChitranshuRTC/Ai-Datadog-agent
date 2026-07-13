"""Logging configuration for the service."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings
from app.logging.context import correlation_id, incident_id, request_id


class JsonFormatter(logging.Formatter):
    """Formats log records as newline-delimited JSON for log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a log record with request correlation metadata."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
            "correlation_id": correlation_id.get(),
            "incident_id": incident_id.get(),
        }
        if hasattr(record, "incident_id"):
            payload["incident_id"] = record.incident_id
        if hasattr(record, "status_code"):
            payload["status"] = record.status_code
        if hasattr(record, "execution_time_ms"):
            payload["execution_time_ms"] = record.execution_time_ms
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging() -> None:
    """Configure process-wide structured, timestamped logging."""
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())
