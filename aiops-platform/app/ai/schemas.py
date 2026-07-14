"""Typed schema for validated Claude CLI remediation responses."""

from dataclasses import dataclass
from enum import StrEnum

from app.models.remediation import RemediationAction


class RiskLevel(StrEnum):
    """Operator-facing risk classification for a proposed remediation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ClaudeRemediationResponse:
    """A validated, schema-conformant remediation proposal returned by Claude."""

    root_cause: str
    confidence: float
    reason: str
    action: RemediationAction
    risk: RiskLevel
    commands: tuple[str, ...]
    verification: str
    github_fix: str | None
    yaml_patch: str | None
