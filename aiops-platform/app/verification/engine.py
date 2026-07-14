"""Post-remediation verification: confirms a remediation actually fixed the incident."""

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.action_engine.kubernetes import KubernetesConnector
from app.connectors.slack import SlackConnector
from app.context.kubernetes import KubernetesContextClient
from app.models.incident import Incident
from app.models.remediation import ActionResult, RemediationAction

_TIMEOUT_BUFFER_SECONDS = 30
_DEFAULT_MAX_ATTEMPTS = 3

_POD_LEVEL_ACTIONS = frozenset({RemediationAction.RESTART_POD, RemediationAction.DELETE_POD})
_NODE_ACTIONS = frozenset({RemediationAction.NODE_CORDON, RemediationAction.NODE_DRAIN})
_NO_VERIFICATION_ACTIONS = frozenset({
    RemediationAction.CREATE_GITHUB_PR,
    RemediationAction.SLACK_NOTIFICATION,
    RemediationAction.COLLECT_LOGS,
    RemediationAction.DESCRIBE_POD,
    RemediationAction.COLLECT_EVENTS,
    RemediationAction.NO_ACTION,
})


class VerificationStatus(StrEnum):
    """Outcome of a post-remediation verification pass."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Structured outcome of a post-remediation verification pass."""

    success: bool
    status: VerificationStatus
    message: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    verification_time: float
    details: dict[str, Any]


class VerificationEngine:
    """Confirms a remediation action actually fixed the incident before closing it out.

    Flow: ActionResult -> wait a configurable duration -> read deployment status,
    pod status, restart count, and ready-replica counts -> read recent events ->
    return a structured VerificationResult and post the outcome to Slack.
    """

    def __init__(
        self,
        kubernetes: KubernetesConnector,
        slack: SlackConnector,
        wait_seconds: int,
        context_client: KubernetesContextClient | None = None,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        timeout_buffer_seconds: float = _TIMEOUT_BUFFER_SECONDS,
    ) -> None:
        self._kubernetes = kubernetes
        self._slack = slack
        self._wait_seconds = wait_seconds
        self._context = context_client or KubernetesContextClient()
        self._max_attempts = max(1, max_attempts)
        self._timeout_buffer_seconds = timeout_buffer_seconds

    async def verify(self, incident: Incident, thread_id: str, result: ActionResult) -> VerificationResult:
        """Verify that an executed remediation action actually resolved the incident."""
        started = time.perf_counter()
        if not result.succeeded:
            return await self._finalize(
                thread_id, VerificationStatus.FAILED, f"❌ Verification failed: remediation action did not succeed ({result.detail}).",
                {}, {}, started, {"action": result.action.value},
            )
        if result.action in _NO_VERIFICATION_ACTIONS:
            return await self._finalize(
                thread_id, VerificationStatus.SUCCESS, f"✅ Remediation completed: {result.detail}",
                {}, {}, started, {"action": result.action.value},
            )
        if result.action in _NODE_ACTIONS:
            await asyncio.sleep(self._wait_seconds)
            return await self._finalize(
                thread_id, VerificationStatus.SUCCESS, f"✅ Remediation completed: {result.detail}",
                {}, {}, started, {"action": result.action.value},
            )

        pod_name = result.resource_name if result.action in _POD_LEVEL_ACTIONS else incident.pod_name
        try:
            before_state, after_state, attempts = await asyncio.wait_for(
                self._observe(incident, result.action, pod_name),
                timeout=self._wait_seconds + self._timeout_buffer_seconds,
            )
        except TimeoutError:
            return await self._finalize(
                thread_id, VerificationStatus.TIMEOUT, "⏱️ Verification timed out waiting for the workload to converge.",
                {}, {}, started, {"action": result.action.value},
            )
        status, message = self._evaluate(result.action, after_state)
        details = {"action": result.action.value, "attempts": attempts}
        return await self._finalize(thread_id, status, message, before_state, after_state, started, details)

    async def _observe(self, incident: Incident, action: RemediationAction, pod_name: str | None) -> tuple[dict[str, Any], dict[str, Any], int]:
        """Capture a before-state snapshot, then poll until the after-state converges."""
        before_state = await self._read_state(incident, action, pod_name)
        after_state, attempts = await self._poll_until_converged(incident, action, pod_name)
        return before_state, after_state, attempts

    async def report_failure(self, thread_id: str) -> VerificationResult:
        """Post an unexpected remediation failure without exposing internal details."""
        message = "❌ Verification failed due to an execution error. Check service logs for details."
        await self._slack.post_thread_update(thread_id, message)
        return VerificationResult(False, VerificationStatus.FAILED, message, {}, {}, 0.0, {})

    async def _poll_until_converged(
        self, incident: Incident, action: RemediationAction, pod_name: str | None
    ) -> tuple[dict[str, Any], int]:
        """Poll workload state a bounded number of times within the configured wait budget."""
        interval = max(0.01, self._wait_seconds / self._max_attempts)
        state: dict[str, Any] = {}
        for attempt in range(1, self._max_attempts + 1):
            await asyncio.sleep(interval)
            state = await self._read_state(incident, action, pod_name)
            if self._is_converged(action, state):
                return state, attempt
        return state, self._max_attempts

    async def _read_state(self, incident: Incident, action: RemediationAction, pod_name: str | None) -> dict[str, Any]:
        """Gather deployment status, pod status, restart count, and recent events."""
        deployment = await self._kubernetes.deployment_status(incident.namespace, incident.service)
        pod = await self._context.get_pod_status(incident.namespace, pod_name) if pod_name else {}
        events = await self._context.get_events(incident.namespace, pod_name) if pod_name else []
        return {
            "deployment": deployment,
            "pod": pod,
            "restart_count": pod.get("restart_count", 0),
            "ready_replicas": deployment.get("available", 0),
            "recent_events": [event.get("reason") for event in events[-5:]],
        }

    @staticmethod
    def _is_converged(action: RemediationAction, state: dict[str, Any]) -> bool:
        """Return whether the workload has already reached its target state."""
        if action in _POD_LEVEL_ACTIONS:
            pod = state.get("pod", {})
            return pod.get("phase") == "Running" and bool(pod.get("ready")) and not pod.get("crash_loop_back_off")
        deployment = state.get("deployment", {})
        desired, available, updated = deployment.get("desired", 0), deployment.get("available", 0), deployment.get("updated", 0)
        return available >= desired and updated >= desired

    @staticmethod
    def _evaluate(action: RemediationAction, state: dict[str, Any]) -> tuple[VerificationStatus, str]:
        """Apply the per-action verification rule to the final observed state."""
        if action in _POD_LEVEL_ACTIONS:
            pod = state.get("pod", {})
            if pod.get("crash_loop_back_off"):
                return VerificationStatus.FAILED, "❌ Verification failed: pods still crashing (CrashLoopBackOff)."
            if pod.get("phase") == "Running" and pod.get("ready"):
                return VerificationStatus.SUCCESS, "✅ Remediation completed: deployment healthy, pods Ready."
            if pod.get("phase") == "Running":
                return VerificationStatus.PARTIAL_SUCCESS, "⚠️ Some pods still unhealthy: pod is Running but not yet Ready."
            return VerificationStatus.FAILED, f"❌ Verification failed: pod is not healthy (phase={pod.get('phase', 'Unknown')})."
        deployment = state.get("deployment", {})
        desired, available, updated = deployment.get("desired", 0), deployment.get("available", 0), deployment.get("updated", 0)
        if available >= desired and updated >= desired:
            return VerificationStatus.SUCCESS, "✅ Remediation completed: deployment healthy, pods Ready."
        if available > 0:
            return VerificationStatus.PARTIAL_SUCCESS, "⚠️ Some pods still unhealthy: deployment is converging but not yet fully ready."
        return VerificationStatus.FAILED, "❌ Verification failed: deployment is not healthy."

    async def _finalize(
        self,
        thread_id: str,
        status: VerificationStatus,
        message: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
        started: float,
        details: dict[str, Any],
    ) -> VerificationResult:
        """Post the outcome to Slack and build the final VerificationResult."""
        await self._slack.post_thread_update(thread_id, message)
        elapsed = round(time.perf_counter() - started, 3)
        success = status is VerificationStatus.SUCCESS
        return VerificationResult(success, status, message, before_state, after_state, elapsed, details)
