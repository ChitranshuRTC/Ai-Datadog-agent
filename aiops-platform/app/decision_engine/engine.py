"""Decision engine combining AI signals, root-cause analysis, and rules."""

from app.ai.engine import AIEngine
from app.models.incident import Incident
from app.models.remediation import RemediationAction, RemediationDecision
from app.decision_engine.root_cause_analyzer import RootCauseAnalyzer
from app.decision_engine.rule_engine import RuleEngine


class DecisionEngine:
    """Produces an explainable remediation decision for an incident."""

    def __init__(self, ai_engine: AIEngine, root_cause_analyzer: RootCauseAnalyzer, rule_engine: RuleEngine) -> None:
        self._ai_engine = ai_engine
        self._root_cause_analyzer = root_cause_analyzer
        self._rule_engine = rule_engine

    def decide(self, incident: Incident) -> RemediationDecision:
        """Analyze the incident and select its matching operational rule."""
        signals = self._ai_engine.analyze(incident)
        root_cause = self._root_cause_analyzer.analyze(incident)
        rule = self._rule_engine.evaluate(signals)
        if rule is None:
            action, reason = self._kubernetes_decision(root_cause.category)
            return RemediationDecision(action, reason, root_cause)
        return RemediationDecision(rule.action, rule.reason, root_cause)

    @staticmethod
    def _kubernetes_decision(category: str) -> tuple[RemediationAction, str]:
        """Choose only actions represented by the established remediation contract."""
        decisions = {
            "CrashLoopBackOff": (RemediationAction.RESTART_POD, "CrashLoopBackOff detected; restart the affected managed pod."),
            "OOMKilled": (RemediationAction.RESTART_POD, "OOMKilled detected; restart the affected managed pod."),
            "Container Restart Loop": (RemediationAction.RESTART_POD, "Container restart loop detected; restart the affected managed pod."),
            "High CPU": (RemediationAction.SCALE_DEPLOYMENT, "High CPU detected; scaling requires an explicit approved replica target."),
            "High Memory": (RemediationAction.CREATE_GITHUB_PR, "High memory detected; propose a reviewed memory-limit change."),
            "ImagePullBackOff": (RemediationAction.COLLECT_LOGS, "Image pull failure detected; collect diagnostics before changing workloads."),
            "Pending Pods": (RemediationAction.SLACK_NOTIFICATION, "Pending pods require scheduler diagnostics and operator review."),
            "FailedScheduling": (RemediationAction.SLACK_NOTIFICATION, "Failed scheduling requires operator review before cluster changes."),
            "Disk Pressure": (RemediationAction.SLACK_NOTIFICATION, "Disk pressure requires operator review before cleanup."),
            "Node Not Ready": (RemediationAction.SLACK_NOTIFICATION, "Node remediation is not performed automatically."),
        }
        return decisions.get(category, (RemediationAction.SLACK_NOTIFICATION, "No automatic remediation rule matched."))
