"""Converts incident context into an explainable Kubernetes root-cause assessment."""

import re
from dataclasses import dataclass

from app.models.incident import Incident
from app.models.remediation import RemediationAction, RootCause


@dataclass(frozen=True, slots=True)
class _CategoryRule:
    """One recognizable Kubernetes failure pattern and its suggested remediation."""

    category: str
    pattern: str
    confidence: float
    evidence: str
    recommended_action: RemediationAction


class RootCauseAnalyzer:
    """Classifies Kubernetes incidents from an incident's title, message, tags, priority, and event type."""

    _RULES: tuple[_CategoryRule, ...] = (
        _CategoryRule(
            "CrashLoopBackOff", r"crashloopbackoff|crash loop back[ -]?off", 0.98,
            "Container continuously exits after startup.", RemediationAction.RESTART_DEPLOYMENT,
        ),
        _CategoryRule(
            "ImagePullBackOff", r"imagepullbackoff|errimagepull|image pull", 0.95,
            "Container image could not be pulled from the registry.", RemediationAction.COLLECT_LOGS,
        ),
        _CategoryRule(
            "OOMKilled", r"oomkilled|out of memory|memory limit exceeded", 0.97,
            "Container was terminated after exceeding its memory limit.", RemediationAction.RESTART_POD,
        ),
        _CategoryRule(
            "ContainerCreating", r"containercreating|container creating", 0.85,
            "Container has remained stuck in the ContainerCreating state.", RemediationAction.COLLECT_LOGS,
        ),
        _CategoryRule(
            "PVCPending", r"pvc.*pending|persistentvolumeclaim.*pending|volume.*pending", 0.9,
            "A PersistentVolumeClaim is unbound and remains in Pending state.", RemediationAction.SLACK_NOTIFICATION,
        ),
        _CategoryRule(
            "FailedScheduling", r"failedscheduling|failed scheduling|unschedulable", 0.95,
            "The scheduler could not place the pod on any node.", RemediationAction.COLLECT_LOGS,
        ),
        _CategoryRule(
            "Pending", r"pending pod|pods? (?:is|are|stuck )?pending", 0.9,
            "A pod remains unscheduled in the Pending phase.", RemediationAction.COLLECT_LOGS,
        ),
        _CategoryRule(
            "NodeNotReady", r"node not ready|nodenotready|node.*notready", 0.95,
            "A node has stopped reporting a Ready condition to the control plane.", RemediationAction.SLACK_NOTIFICATION,
        ),
        _CategoryRule(
            "DiskPressure", r"diskpressure|disk pressure|disk full|no space left|filesystem.*(?:full|usage)", 0.9,
            "A node is reporting disk pressure from insufficient ephemeral storage.", RemediationAction.SLACK_NOTIFICATION,
        ),
        _CategoryRule(
            "MemoryPressure", r"memorypressure|memory pressure|node.*(?:low|out) of memory", 0.9,
            "A node is reporting memory pressure and may begin evicting pods.", RemediationAction.RESTART_POD,
        ),
        _CategoryRule(
            "DeploymentUnavailable", r"deploymentunavailable|deployment.*unavailable|minimumreplicasunavailable", 0.93,
            "The deployment does not have the minimum number of available replicas.", RemediationAction.RESTART_DEPLOYMENT,
        ),
        _CategoryRule(
            "ContainerRestartLoop", r"container restart loop|restarting container|back-off restarting", 0.92,
            "The container is being repeatedly restarted by its kubelet back-off policy.", RemediationAction.RESTART_POD,
        ),
        _CategoryRule(
            "HighCPU", r"high cpu|cpu (?:usage|utilization|saturation)|cpu throttling", 0.9,
            "Sustained high CPU utilization was detected on the workload.", RemediationAction.SCALE_DEPLOYMENT,
        ),
        _CategoryRule(
            "HighMemory", r"high memory|memory (?:usage|utilization)|heap", 0.9,
            "Sustained high memory utilization was detected on the workload.", RemediationAction.RESTART_POD,
        ),
    )

    _UNKNOWN = RootCause(
        category="Unknown", confidence=0.0,
        evidence="No supported Kubernetes incident type was detected.",
        recommended_action=RemediationAction.SLACK_NOTIFICATION,
    )

    def analyze(self, incident: Incident) -> RootCause:
        """Classify a Kubernetes incident from its title, message, tags, priority, and event type."""
        text = self._searchable_text(incident)
        for rule in self._RULES:
            if re.search(rule.pattern, text):
                return RootCause(rule.category, rule.confidence, rule.evidence, rule.recommended_action)
        return self._UNKNOWN

    @staticmethod
    def _searchable_text(incident: Incident) -> str:
        """Combine every incident signal the classifier considers into one lowercase blob."""
        tag_text = " ".join(f"{key}:{value}" for key, value in incident.tags.items())
        parts = (incident.title, incident.watchdog_summary, tag_text, incident.priority, incident.event_type)
        return " ".join(part for part in parts if part).lower()
