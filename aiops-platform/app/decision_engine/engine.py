"""Decision engine combining AI signals, root-cause analysis, rules, and Claude CLI."""

import logging

from app.ai.claude_cli import ClaudeCLIClient, ClaudeCLIError
from app.ai.engine import AIEngine
from app.ai.prompt_builder import ClaudePromptBuilder
from app.ai.response_parser import ClaudeResponseError, ResponseParser
from app.models.incident import Incident
from app.models.remediation import RemediationDecision, RootCause
from app.decision_engine.root_cause_analyzer import RootCauseAnalyzer
from app.decision_engine.rule_engine import RuleEngine

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Produces an explainable remediation decision for an incident."""

    def __init__(
        self,
        ai_engine: AIEngine,
        root_cause_analyzer: RootCauseAnalyzer,
        rule_engine: RuleEngine,
        claude: ClaudeCLIClient | None = None,
        claude_prompt_builder: ClaudePromptBuilder | None = None,
        response_parser: ResponseParser | None = None,
    ) -> None:
        self._ai_engine = ai_engine
        self._root_cause_analyzer = root_cause_analyzer
        self._rule_engine = rule_engine
        self._claude = claude or ClaudeCLIClient()
        self._claude_prompt_builder = claude_prompt_builder or ClaudePromptBuilder()
        self._response_parser = response_parser or ResponseParser()

    def decide(self, incident: Incident) -> RemediationDecision:
        """Analyze the incident, classify its root cause, and select a remediation decision.

        A fast, deterministic AI-signal rule always takes priority when one matches.
        Otherwise Claude CLI is consulted for a schema-validated recommendation, with
        the regex-based root-cause mapping as a safety net if Claude is unavailable
        or returns an invalid response.
        """
        signals = self._ai_engine.analyze(incident)
        root_cause = self._root_cause_analyzer.analyze(incident)
        rule = self._rule_engine.evaluate(signals)
        if rule is not None:
            return RemediationDecision(rule.action, rule.reason, root_cause)
        return self._decide_with_claude(incident, root_cause)

    def _decide_with_claude(self, incident: Incident, root_cause: RootCause) -> RemediationDecision:
        """Build a prompt, call Claude CLI, and validate its JSON response into a decision."""
        try:
            prompt = self._claude_prompt_builder.build(incident)
            raw_response = self._claude.run(prompt)
            parsed = self._response_parser.parse(raw_response)
        except (ClaudeCLIError, ClaudeResponseError):
            logger.warning("Claude CLI decision unavailable for incident %s; using rule-based root cause mapping.", incident.identifier)
            return self._rule_engine.evaluate_root_cause(root_cause)
        claude_root_cause = RootCause(
            category=parsed.root_cause,
            confidence=parsed.confidence,
            evidence=parsed.reason,
            recommended_action=parsed.action,
        )
        return RemediationDecision(parsed.action, parsed.reason, claude_root_cause, parsed.github_fix, parsed.yaml_patch)
