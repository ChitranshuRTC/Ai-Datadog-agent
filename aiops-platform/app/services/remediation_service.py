"""End-to-end automated remediation orchestration."""

import logging

from app.action_engine.engine import KubernetesActionEngine
from app.connectors.github_ai import GitHubAIConnector
from app.connectors.slack import SlackConnector
from app.decision_engine.engine import DecisionEngine
from app.models.incident import Incident
from app.models.remediation import RemediationDecision
from app.verification.engine import VerificationEngine, VerificationResult

logger = logging.getLogger(__name__)


class RemediationService:
    """Decides, executes, verifies, and reports a remediation lifecycle."""

    def __init__(
        self,
        decision_engine: DecisionEngine,
        action_engine: KubernetesActionEngine,
        verification_engine: VerificationEngine,
        github_ai: GitHubAIConnector | None = None,
        slack: SlackConnector | None = None,
    ) -> None:
        self._decision_engine = decision_engine
        self._action_engine = action_engine
        self._verification_engine = verification_engine
        self._github_ai = github_ai
        self._slack = slack

    async def remediate(self, incident: Incident, slack_thread_id: str) -> VerificationResult:
        """Run Decision -> Execute -> Verify -> (optional GitHub PR) -> Slack update."""
        decision = self._decision_engine.decide(incident)
        try:
            result = await self._action_engine.execute(incident, decision, incident.pod_name)
            verification = await self._verification_engine.verify(incident, slack_thread_id, result)
            if decision.github_fix:
                await self._create_pull_request(incident, decision, slack_thread_id)
            return verification
        except Exception:
            logger.exception("Remediation execution failed for incident %s", incident.identifier)
            return await self._verification_engine.report_failure(slack_thread_id)

    async def _create_pull_request(self, incident: Incident, decision: RemediationDecision, slack_thread_id: str) -> None:
        """Open a GitHub pull request for Claude's proposed YAML fix and report the outcome."""
        if self._github_ai is None or self._slack is None:
            return
        if not decision.yaml_patch:
            logger.warning("Claude proposed a GitHub fix for incident %s without a yaml_patch; skipping PR creation.", incident.identifier)
            return
        pr_result = await self._github_ai.create_remediation_pull_request(
            incident.identifier, incident.service, decision.github_fix, decision.yaml_patch
        )
        if pr_result.success:
            message = (
                "🔧 GitHub PR Created\n"
                f"PR URL: {pr_result.url}\n"
                f"Branch: {pr_result.branch}\n"
                f"Commit: {pr_result.commit_sha}"
            )
        else:
            message = f"⚠️ GitHub PR automation failed: {pr_result.message}"
        await self._slack.post_thread_update(slack_thread_id, message)
