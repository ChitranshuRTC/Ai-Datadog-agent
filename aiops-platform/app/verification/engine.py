"""Post-remediation health verification and Slack thread status updates."""

import asyncio
from enum import StrEnum

from app.action_engine.kubernetes import KubernetesConnector
from app.connectors.slack import SlackConnector
from app.models.incident import Incident
from app.models.remediation import ActionResult, RemediationAction


class VerificationStatus(StrEnum):
    """Outcome of a post-remediation verification pass."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"
    TIMEOUT = "timeout"


class VerificationEngine:
    """Waits for workload convergence and reports outcome in the incident thread."""

    _NO_VERIFICATION_ACTIONS = frozenset({
        RemediationAction.CREATE_GITHUB_PR,
        RemediationAction.SLACK_NOTIFICATION,
        RemediationAction.COLLECT_LOGS,
        RemediationAction.DESCRIBE_POD,
        RemediationAction.COLLECT_EVENTS,
        RemediationAction.NO_ACTION,
    })
    _NODE_ACTIONS = frozenset({RemediationAction.NODE_CORDON, RemediationAction.NODE_DRAIN})

    def __init__(self, kubernetes: KubernetesConnector, slack: SlackConnector, wait_seconds: int) -> None:
        self._kubernetes = kubernetes
        self._slack = slack
        self._wait_seconds = wait_seconds

    async def verify(self, incident: Incident, thread_id: str, result: ActionResult) -> VerificationStatus:
        """Wait after action, verify deployment health, and update the Slack thread."""
        if not result.succeeded:
            await self._slack.post_thread_update(thread_id, f"❌ Remediation failed: {result.detail}")
            return VerificationStatus.FAILED
        if result.action in self._NO_VERIFICATION_ACTIONS:
            await self._slack.post_thread_update(thread_id, f"✅ Remediation completed: {result.detail}")
            return VerificationStatus.SUCCESS
        if result.action in self._NODE_ACTIONS:
            await asyncio.sleep(self._wait_seconds)
            await self._slack.post_thread_update(thread_id, f"✅ Remediation completed: {result.detail}")
            return VerificationStatus.SUCCESS
        try:
            healthy = await asyncio.wait_for(self._await_health(incident), timeout=self._wait_seconds + 30)
        except TimeoutError:
            await self._slack.post_thread_update(thread_id, "⏱️ Remediation verification timed out waiting for the deployment to converge.")
            return VerificationStatus.TIMEOUT
        if healthy:
            await self._slack.post_thread_update(thread_id, "✅ Remediation verified: deployment is healthy.")
            return VerificationStatus.SUCCESS
        status = await self._kubernetes.deployment_status(incident.namespace, incident.service)
        if status["available"] > 0:
            await self._slack.post_thread_update(thread_id, "⚠️ Remediation partially verified: deployment is converging but not yet fully healthy.")
            return VerificationStatus.PARTIAL_SUCCESS
        await self._slack.post_thread_update(thread_id, "❌ Remediation failed verification: deployment is not healthy.")
        return VerificationStatus.FAILED

    async def _await_health(self, incident: Incident) -> bool:
        await asyncio.sleep(self._wait_seconds)
        return await self._kubernetes.deployment_healthy(incident.namespace, incident.service)

    async def report_failure(self, thread_id: str) -> None:
        """Post an unexpected remediation failure without exposing internal details."""
        await self._slack.post_thread_update(thread_id, "❌ Remediation failed due to an execution error. Check service logs for details.")
