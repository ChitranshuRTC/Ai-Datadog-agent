"""Post-remediation health verification and Slack thread status updates."""

import asyncio

from app.action_engine.kubernetes import KubernetesConnector
from app.connectors.slack import SlackConnector
from app.models.incident import Incident
from app.models.remediation import ActionResult


class VerificationEngine:
    """Waits for workload convergence and reports outcome in the incident thread."""

    def __init__(self, kubernetes: KubernetesConnector, slack: SlackConnector, wait_seconds: int) -> None:
        self._kubernetes = kubernetes
        self._slack = slack
        self._wait_seconds = wait_seconds

    async def verify(self, incident: Incident, thread_id: str, result: ActionResult) -> bool:
        """Wait after action, verify deployment health, and update the Slack thread."""
        if not result.succeeded:
            await self._slack.post_thread_update(thread_id, f"❌ Remediation failed: {result.detail}")
            return False
        await asyncio.sleep(self._wait_seconds)
        if result.action.value in {"create_github_pr", "slack_notification", "collect_logs"}:
            await self._slack.post_thread_update(thread_id, f"✅ Remediation completed: {result.detail}")
            return True
        healthy = await self._kubernetes.deployment_healthy(incident.namespace, incident.service)
        message = "✅ Remediation verified: deployment is healthy." if healthy else "❌ Remediation failed verification: deployment is not healthy."
        await self._slack.post_thread_update(thread_id, message)
        return healthy

    async def report_failure(self, thread_id: str) -> None:
        """Post an unexpected remediation failure without exposing internal details."""
        await self._slack.post_thread_update(thread_id, "❌ Remediation failed due to an execution error. Check service logs for details.")
