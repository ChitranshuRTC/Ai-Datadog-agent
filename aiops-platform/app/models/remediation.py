"""Domain types for automated remediation decisions and results."""

from dataclasses import dataclass
from enum import StrEnum


class RemediationAction(StrEnum):
    """Actions the platform can recommend or execute."""

    RESTART_POD = "restart_pod"
    RESTART_DEPLOYMENT = "restart_deployment"
    SCALE_DEPLOYMENT = "scale_deployment"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    DELETE_POD = "delete_pod"
    COLLECT_LOGS = "collect_logs"
    CREATE_GITHUB_PR = "create_github_pr"
    SLACK_NOTIFICATION = "slack_notification"


@dataclass(frozen=True, slots=True)
class RootCause:
    """A classified likely cause and the supporting evidence."""

    category: str
    confidence: float
    evidence: str


@dataclass(frozen=True, slots=True)
class RemediationDecision:
    """An explainable action selected for an incident."""

    action: RemediationAction
    reason: str
    root_cause: RootCause


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Result of an external remediation operation."""

    action: RemediationAction
    succeeded: bool
    detail: str
    resource_name: str | None = None
    pull_request_url: str | None = None
