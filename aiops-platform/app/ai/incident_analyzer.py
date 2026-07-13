"""Explainable incident signal extraction."""

import re

from app.models.incident import Incident


class IncidentAnalyzer:
    """Extracts normalized diagnostic signals from Datadog incident text."""

    def analyze(self, incident: Incident, prompt: str) -> set[str]:
        """Return relevant signals; the prompt is retained for auditable AI-engine input."""
        del prompt
        text = f"{incident.title} {incident.watchdog_summary}".lower()
        patterns = {
            "oom_killed": r"oomkilled|out of memory|memory limit",
            "high_memory": r"high memory|memory (usage|utilization)|heap",
            "post_deploy_latency": r"latency.*(?:deploy|release)|(?:deploy|release).*latency",
            "disk_full": r"disk full|no space left|filesystem.*(?:full|usage)",
        }
        return {name for name, pattern in patterns.items() if re.search(pattern, text)}
