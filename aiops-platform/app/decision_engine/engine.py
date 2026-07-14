"""Decision engine combining AI signals, root-cause analysis, and rules."""

from app.ai.engine import AIEngine
from app.models.incident import Incident
from app.models.remediation import RemediationDecision
from app.decision_engine.root_cause_analyzer import RootCauseAnalyzer
from app.decision_engine.rule_engine import RuleEngine


class DecisionEngine:
    """Produces an explainable remediation decision for an incident."""

    def __init__(self, ai_engine: AIEngine, root_cause_analyzer: RootCauseAnalyzer, rule_engine: RuleEngine) -> None:
        self._ai_engine = ai_engine
        self._root_cause_analyzer = root_cause_analyzer
        self._rule_engine = rule_engine

    def decide(self, incident: Incident) -> RemediationDecision:
        """Analyze the incident, classify its root cause, and select a remediation decision."""
        signals = self._ai_engine.analyze(incident)
        root_cause = self._root_cause_analyzer.analyze(incident)
        rule = self._rule_engine.evaluate(signals)
        if rule is not None:
            return RemediationDecision(rule.action, rule.reason, root_cause)
        return self._rule_engine.evaluate_root_cause(root_cause)
