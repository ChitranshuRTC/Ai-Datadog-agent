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
    PATCH_MEMORY = "patch_memory"
    PATCH_CPU = "patch_cpu"
    DESCRIBE_POD = "describe_pod"
    COLLECT_EVENTS = "collect_events"
    NODE_CORDON = "node_cordon"
    NODE_DRAIN = "node_drain"
    NO_ACTION = "no_action"


@dataclass(frozen=True, slots=True)
class RootCause:
    """A classified likely cause, its supporting evidence, and the suggested remediation."""

    category: str
    confidence: float
    evidence: str
    recommended_action: RemediationAction


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
