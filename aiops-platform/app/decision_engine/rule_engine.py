"""Declarative rule selection for safe and explainable remediation."""

from dataclasses import dataclass

from app.models.remediation import RemediationAction, RemediationDecision, RootCause


@dataclass(frozen=True, slots=True)
class RemediationRule:
    """Maps one incident signal to a remediation action."""

    signal: str
    action: RemediationAction
    reason: str


class RuleEngine:
    """Evaluates the ordered, deterministic remediation rule set."""

    _ROOT_CAUSE_ACTIONS: dict[str, tuple[RemediationAction, str]] = {
        "CrashLoopBackOff": (RemediationAction.RESTART_DEPLOYMENT, "CrashLoopBackOff detected; rolling restart the affected deployment."),
        "ImagePullBackOff": (RemediationAction.COLLECT_LOGS, "Image pull failure detected; collect diagnostics before changing workloads."),
        "OOMKilled": (RemediationAction.CREATE_GITHUB_PR, "OOMKilled detected; propose a reviewed memory-limit change."),
        "Pending Pods": (RemediationAction.DESCRIBE_POD, "Pending pods detected; describe the pod to surface scheduler diagnostics."),
        "FailedScheduling": (RemediationAction.DESCRIBE_POD, "Failed scheduling detected; describe the pod to surface placement constraints."),
        "ContainerCreating timeout": (RemediationAction.DESCRIBE_POD, "Container stuck creating; describe the pod to diagnose the startup stall."),
        "NodeNotReady": (RemediationAction.NODE_CORDON, "Node not ready; cordon the node so no new pods are scheduled on it."),
        "DiskPressure": (RemediationAction.NODE_DRAIN, "Disk pressure detected; drain the node before it is repaired or replaced."),
        "MemoryPressure": (RemediationAction.NODE_DRAIN, "Memory pressure detected; drain the node before it evicts pods on its own."),
        "High CPU": (RemediationAction.SCALE_DEPLOYMENT, "High CPU detected; scaling requires an explicit approved replica target."),
        "High Memory": (RemediationAction.RESTART_POD, "High memory detected; restart the affected managed pod."),
        "Container Restart Loop": (RemediationAction.RESTART_POD, "Container restart loop detected; restart the affected managed pod."),
        "DeploymentUnavailable": (RemediationAction.RESTART_DEPLOYMENT, "Deployment unavailable; rolling restart the affected deployment."),
        "PVC Pending": (RemediationAction.COLLECT_EVENTS, "PVC pending detected; collect events to diagnose the unbound volume claim."),
    }
    _DEFAULT_ROOT_CAUSE_ACTION = (RemediationAction.SLACK_NOTIFICATION, "No automatic remediation rule matched.")

    def __init__(self, rules: tuple[RemediationRule, ...] | None = None) -> None:
        self._rules = rules or (
            RemediationRule("oom_killed", RemediationAction.RESTART_POD, "Container was terminated because it exceeded its memory limit."),
            RemediationRule("high_memory", RemediationAction.CREATE_GITHUB_PR, "Sustained memory pressure requires a reviewed configuration change."),
            RemediationRule("post_deploy_latency", RemediationAction.ROLLBACK_DEPLOYMENT, "Latency regression was detected after a deployment."),
            RemediationRule("disk_full", RemediationAction.SLACK_NOTIFICATION, "Disk pressure requires operator review before destructive cleanup."),
        )

    def evaluate(self, signals: set[str]) -> RemediationRule | None:
        """Return the highest-priority rule matching the analyzed AI signals."""
        return next((rule for rule in self._rules if rule.signal in signals), None)

    def evaluate_root_cause(self, root_cause: RootCause) -> RemediationDecision:
        """Convert a classified Kubernetes root cause into an explainable remediation decision."""
        action, reason = self._ROOT_CAUSE_ACTIONS.get(root_cause.category, self._DEFAULT_ROOT_CAUSE_ACTION)
        return RemediationDecision(action, reason, root_cause)
