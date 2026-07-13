"""Declarative rule selection for safe and explainable remediation."""

from dataclasses import dataclass

from app.models.remediation import RemediationAction


@dataclass(frozen=True, slots=True)
class RemediationRule:
    """Maps one incident signal to a remediation action."""

    signal: str
    action: RemediationAction
    reason: str


class RuleEngine:
    """Evaluates the ordered, deterministic remediation rule set."""

    def __init__(self, rules: tuple[RemediationRule, ...] | None = None) -> None:
        self._rules = rules or (
            RemediationRule("oom_killed", RemediationAction.RESTART_POD, "Container was terminated because it exceeded its memory limit."),
            RemediationRule("high_memory", RemediationAction.CREATE_GITHUB_PR, "Sustained memory pressure requires a reviewed configuration change."),
            RemediationRule("post_deploy_latency", RemediationAction.ROLLBACK_DEPLOYMENT, "Latency regression was detected after a deployment."),
            RemediationRule("disk_full", RemediationAction.SLACK_NOTIFICATION, "Disk pressure requires operator review before destructive cleanup."),
        )

    def evaluate(self, signals: set[str]) -> RemediationRule | None:
        """Return the highest-priority rule matching the analyzed signals."""
        return next((rule for rule in self._rules if rule.signal in signals), None)
