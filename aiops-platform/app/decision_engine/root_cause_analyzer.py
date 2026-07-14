"""Converts incident context into an explainable Kubernetes root-cause assessment."""

import re

from app.models.incident import Incident
from app.models.remediation import RootCause


class RootCauseAnalyzer:
    """Assigns confidence to known operational failure patterns."""

    _PATTERNS: tuple[tuple[str, str], ...] = (
        ("CrashLoopBackOff", r"crashloopbackoff|crash loop back[ -]?off"),
        ("ImagePullBackOff", r"imagepullbackoff|errimagepull|image pull"),
        ("OOMKilled", r"oomkilled|out of memory|memory limit exceeded"),
        ("Pending Pods", r"pending pod|pods? (?:is|are|stuck )?pending"),
        ("FailedScheduling", r"failedscheduling|failed scheduling|unschedulable"),
        ("High CPU", r"high cpu|cpu (?:usage|utilization|saturation)|cpu throttling"),
        ("High Memory", r"high memory|memory (?:usage|utilization|pressure)|heap"),
        ("Disk Pressure", r"disk pressure|disk full|no space left|filesystem.*(?:full|usage)"),
        ("Node Not Ready", r"node not ready|node.*notready"),
        ("Container Restart Loop", r"container restart loop|restarting container|back-off restarting"),
    )

    def analyze(self, incident: Incident | set[str]) -> RootCause:
        """Classify Kubernetes incidents from normalized incident context.

        The set form remains supported for existing signal-based callers.
        """
        if isinstance(incident, set):
            if incident:
                category = sorted(incident)[0]
                return RootCause(category=category, confidence=0.9, evidence=f"Detected signal: {category}")
            return RootCause(category="Unknown", confidence=0.0, evidence="No supported remediation signal was detected.")

        tag_text = " ".join(f"{key}:{value}" for key, value in incident.tags.items())
        text = " ".join(part for part in (incident.title, incident.watchdog_summary, tag_text) if part).lower()
        for category, pattern in self._PATTERNS:
            match = re.search(pattern, text)
            if match:
                return RootCause(category=category, confidence=0.95, evidence=f"Matched Kubernetes signal: {match.group(0)}")
        return RootCause(category="Unknown", confidence=0.0, evidence="No supported Kubernetes incident type was detected.")
