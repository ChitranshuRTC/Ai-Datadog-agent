"""Validates and parses Claude CLI remediation responses into a typed schema."""

import json
from typing import Any

from app.ai.schemas import ClaudeRemediationResponse, RiskLevel
from app.models.remediation import RemediationAction


class ClaudeResponseError(ValueError):
    """Raised when a Claude CLI response is malformed or fails schema validation."""


class ResponseParser:
    """Parses raw Claude CLI text output into a validated ClaudeRemediationResponse."""

    _REQUIRED_FIELDS = ("root_cause", "confidence", "reason", "action", "risk", "verification")

    def parse(self, raw_response: str) -> ClaudeRemediationResponse:
        """Parse and validate a raw Claude response, raising on any schema violation."""
        payload = self._decode_json(raw_response)
        self._require_fields(payload)
        return ClaudeRemediationResponse(
            root_cause=str(payload["root_cause"]).strip(),
            confidence=self._validate_confidence(payload["confidence"]),
            reason=str(payload["reason"]).strip(),
            action=self._validate_action(payload["action"]),
            risk=self._validate_risk(payload["risk"]),
            commands=self._validate_commands(payload.get("commands", [])),
            verification=str(payload["verification"]).strip(),
            github_fix=self._optional_string(payload.get("github_fix")),
            yaml_patch=self._optional_string(payload.get("yaml_patch")),
        )

    @staticmethod
    def _decode_json(raw_response: str) -> dict[str, Any]:
        """Extract and decode the JSON object embedded in a Claude text response."""
        text = raw_response.strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ClaudeResponseError("Claude response did not contain a JSON object.")
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ClaudeResponseError("Claude response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ClaudeResponseError("Claude response JSON must be an object.")
        return payload

    @classmethod
    def _require_fields(cls, payload: dict[str, Any]) -> None:
        missing = [field for field in cls._REQUIRED_FIELDS if field not in payload or payload[field] in (None, "")]
        if missing:
            raise ClaudeResponseError(f"Claude response is missing required fields: {', '.join(missing)}.")

    @staticmethod
    def _validate_action(value: Any) -> RemediationAction:
        try:
            return RemediationAction(str(value).strip().lower())
        except ValueError as exc:
            raise ClaudeResponseError(f"Claude response proposed an unknown action: {value!r}.") from exc

    @staticmethod
    def _validate_risk(value: Any) -> RiskLevel:
        try:
            return RiskLevel(str(value).strip().lower())
        except ValueError as exc:
            raise ClaudeResponseError(f"Claude response proposed an unknown risk level: {value!r}.") from exc

    @staticmethod
    def _validate_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError) as exc:
            raise ClaudeResponseError(f"Claude response confidence must be numeric: {value!r}.") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ClaudeResponseError(f"Claude response confidence must be between 0.0 and 1.0: {confidence!r}.")
        return confidence

    @staticmethod
    def _validate_commands(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ClaudeResponseError("Claude response 'commands' must be a list of strings.")
        return tuple(value)

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
