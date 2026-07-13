"""Datadog payload parsing and webhook authentication."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status

from app.config.settings import Settings
from app.models.incident import Incident, IncidentSeverity


class DatadogWebhookValidator:
    """Validates a configured shared token and optional payload HMAC signature."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.datadog_webhook_token
        self._hmac_secret = settings.datadog_webhook_hmac_secret

    async def validate(self, request: Request, raw_body: bytes) -> None:
        """Reject requests that do not prove knowledge of configured credentials."""
        if self._token is None and self._hmac_secret is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Datadog webhook authentication is not configured.",
            )
        if self._token is not None:
            provided = request.headers.get("X-Datadog-Webhook-Token", "")
            if not hmac.compare_digest(provided, self._token.get_secret_value()):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token.")
        if self._hmac_secret is not None:
            signature = request.headers.get("X-Datadog-Signature", "")
            expected = hmac.new(
                self._hmac_secret.get_secret_value().encode(), raw_body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature.")


class DatadogConnector:
    """Converts Datadog monitor and Watchdog webhook payloads into incidents."""

    def parse_incident(self, raw_body: bytes) -> Incident:
        """Parse a JSON Datadog webhook payload into the AIOps incident model."""
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Webhook body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Webhook payload must be a JSON object.")

        title = self._string(payload, "title", "alert_title", default="Datadog incident")
        identifier = self._string(payload, "id", "alert_id", "event_id", default=self._stable_identifier(payload))
        tags = self._tags(payload)
        return Incident(
            identifier=identifier,
            title=title,
            severity=self._severity(self._string(payload, "alert_status", "severity", "priority", default="unknown")),
            namespace=tags.get("namespace", self._string(payload, "namespace", default="unknown")),
            service=tags.get("service", self._string(payload, "service", default="unknown")),
            cluster=tags.get("cluster_name", tags.get("cluster", self._string(payload, "cluster", default="unknown"))),
            occurred_at=self._timestamp(payload),
            watchdog_summary=self._string(payload, "watchdog_summary", "text", "body", default="No Watchdog summary provided."),
            pod_name=tags.get("pod_name", tags.get("pod", None)),
        )

    @staticmethod
    def _string(payload: dict[str, Any], *keys: str, default: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return default

    @staticmethod
    def _tags(payload: dict[str, Any]) -> dict[str, str]:
        raw_tags = payload.get("tags", [])
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.split(",")
        if not isinstance(raw_tags, list):
            return {}
        result: dict[str, str] = {}
        for tag in raw_tags:
            if isinstance(tag, str) and ":" in tag:
                key, value = tag.split(":", 1)
                result[key.strip()] = value.strip()
        return result

    @staticmethod
    def _severity(value: str) -> IncidentSeverity:
        normalized = value.lower()
        if normalized in {"alert", "critical", "error", "p1"}:
            return IncidentSeverity.CRITICAL
        if normalized in {"warn", "warning", "p2"}:
            return IncidentSeverity.WARNING
        if normalized in {"ok", "info", "notice", "p3"}:
            return IncidentSeverity.INFO
        return IncidentSeverity.UNKNOWN

    @staticmethod
    def _timestamp(payload: dict[str, Any]) -> datetime:
        value = payload.get("date") or payload.get("timestamp") or payload.get("last_updated")
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                pass
        return datetime.now(tz=UTC)

    @staticmethod
    def _stable_identifier(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()[:24]
