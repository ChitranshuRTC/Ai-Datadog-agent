"""Tests for explainable AIOps remediation selection."""

from datetime import UTC, datetime

from app.ai.engine import AIEngine
from app.ai.incident_analyzer import IncidentAnalyzer
from app.ai.prompt_builder import PromptBuilder
from app.decision_engine.engine import DecisionEngine
from app.decision_engine.root_cause_analyzer import RootCauseAnalyzer
from app.decision_engine.rule_engine import RuleEngine
from app.models.incident import Incident, IncidentSeverity
from app.models.remediation import RemediationAction


def _engine() -> DecisionEngine:
    return DecisionEngine(AIEngine(PromptBuilder(), IncidentAnalyzer()), RootCauseAnalyzer(), RuleEngine())


def test_oom_killed_restarts_pod() -> None:
    incident = Incident("1", "OOMKilled", IncidentSeverity.CRITICAL, "ns", "api", "cluster", datetime.now(UTC), "Container OOMKilled")

    assert _engine().decide(incident).action is RemediationAction.RESTART_POD


def test_latency_after_deployment_rolls_back() -> None:
    incident = Incident("1", "Latency after deployment", IncidentSeverity.CRITICAL, "ns", "api", "cluster", datetime.now(UTC), "Latency regression after release")

    assert _engine().decide(incident).action is RemediationAction.ROLLBACK_DEPLOYMENT
