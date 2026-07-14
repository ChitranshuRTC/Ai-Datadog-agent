"""Tests for post-remediation verification, mocking the Kubernetes clients."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.models.incident import Incident, IncidentSeverity
from app.models.remediation import ActionResult, RemediationAction
from app.verification.engine import VerificationEngine, VerificationResult, VerificationStatus


class FakeKubernetes:
    """Fake action-engine Kubernetes connector returning a fixed deployment status."""

    def __init__(self, deployment_status: dict | None = None) -> None:
        self._deployment_status = deployment_status or {"desired": 1, "available": 1, "updated": 1}
        self.calls = 0

    async def deployment_status(self, namespace: str, name: str) -> dict:
        self.calls += 1
        return self._deployment_status


class SlowFakeKubernetes:
    """Fake connector that never responds within the test's timeout budget."""

    async def deployment_status(self, namespace: str, name: str) -> dict:
        await asyncio.sleep(10)
        return {"desired": 1, "available": 1, "updated": 1}


class UnreachableFakeKubernetes:
    """Fake connector that fails the test if it is ever called."""

    async def deployment_status(self, namespace: str, name: str) -> dict:
        raise AssertionError("deployment_status should not be called when the action already failed.")


class FakeContext:
    """Fake context client returning a fixed pod status and no events."""

    def __init__(self, pod_status: dict | None = None) -> None:
        self._pod_status = pod_status or {}

    async def get_pod_status(self, namespace: str, pod: str) -> dict:
        return self._pod_status

    async def get_events(self, namespace: str, pod: str) -> list:
        return []


class FakeSlack:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def post_thread_update(self, thread_id: str, text: str) -> None:
        self.messages.append(text)


def _incident() -> Incident:
    return Incident("1", "Alert", IncidentSeverity.CRITICAL, "ns", "api", "cluster", datetime.now(UTC), "summary")


@pytest.mark.asyncio
async def test_success_when_deployment_fully_available() -> None:
    kubernetes = FakeKubernetes({"desired": 3, "available": 3, "updated": 3})
    slack = FakeSlack()
    engine = VerificationEngine(kubernetes, slack, wait_seconds=0.01, context_client=FakeContext(), max_attempts=1)
    result = ActionResult(RemediationAction.RESTART_DEPLOYMENT, True, "Restarted", "api")

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert isinstance(outcome, VerificationResult)
    assert outcome.status is VerificationStatus.SUCCESS
    assert outcome.success is True
    assert "healthy" in outcome.message
    assert slack.messages == [outcome.message]


@pytest.mark.asyncio
async def test_failed_when_deployment_has_no_available_replicas() -> None:
    kubernetes = FakeKubernetes({"desired": 3, "available": 0, "updated": 0})
    slack = FakeSlack()
    engine = VerificationEngine(kubernetes, slack, wait_seconds=0.01, context_client=FakeContext(), max_attempts=1)
    result = ActionResult(RemediationAction.SCALE_DEPLOYMENT, True, "Scaled", "api")

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert outcome.status is VerificationStatus.FAILED
    assert outcome.success is False
    assert "not healthy" in outcome.message


@pytest.mark.asyncio
async def test_partial_success_when_some_replicas_ready() -> None:
    kubernetes = FakeKubernetes({"desired": 3, "available": 1, "updated": 1})
    slack = FakeSlack()
    engine = VerificationEngine(kubernetes, slack, wait_seconds=0.01, context_client=FakeContext(), max_attempts=1)
    result = ActionResult(RemediationAction.PATCH_MEMORY, True, "Patched", "api")

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert outcome.status is VerificationStatus.PARTIAL_SUCCESS
    assert outcome.success is False
    assert "still unhealthy" in outcome.message


@pytest.mark.asyncio
async def test_timeout_when_kubernetes_read_hangs() -> None:
    slack = FakeSlack()
    engine = VerificationEngine(SlowFakeKubernetes(), slack, wait_seconds=0.01, context_client=FakeContext(), max_attempts=1, timeout_buffer_seconds=0.01)
    result = ActionResult(RemediationAction.RESTART_DEPLOYMENT, True, "Restarted", "api")

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert outcome.status is VerificationStatus.TIMEOUT
    assert outcome.success is False
    assert "timed out" in outcome.message


@pytest.mark.asyncio
async def test_pod_level_crash_loop_back_off_fails() -> None:
    context = FakeContext({"phase": "Running", "ready": False, "crash_loop_back_off": True, "restart_count": 9, "waiting_reason": "CrashLoopBackOff"})
    slack = FakeSlack()
    engine = VerificationEngine(FakeKubernetes(), slack, wait_seconds=0.01, context_client=context, max_attempts=1)
    result = ActionResult(RemediationAction.RESTART_POD, True, "Pod restarted", "api-abc123")

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert outcome.status is VerificationStatus.FAILED
    assert "crashing" in outcome.message


@pytest.mark.asyncio
async def test_pod_level_success_when_running_and_ready() -> None:
    context = FakeContext({"phase": "Running", "ready": True, "crash_loop_back_off": False, "restart_count": 0, "waiting_reason": None})
    slack = FakeSlack()
    engine = VerificationEngine(FakeKubernetes(), slack, wait_seconds=0.01, context_client=context, max_attempts=1)
    result = ActionResult(RemediationAction.RESTART_POD, True, "Pod restarted", "api-abc123")

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert outcome.status is VerificationStatus.SUCCESS
    assert outcome.success is True


@pytest.mark.asyncio
async def test_action_failure_short_circuits_without_reading_cluster_state() -> None:
    slack = FakeSlack()
    engine = VerificationEngine(UnreachableFakeKubernetes(), slack, wait_seconds=0.01, context_client=FakeContext())
    result = ActionResult(RemediationAction.RESTART_POD, False, "A pod name is required to restart a pod.", None)

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert outcome.status is VerificationStatus.FAILED
    assert outcome.success is False


@pytest.mark.asyncio
async def test_no_verification_action_returns_success_immediately() -> None:
    slack = FakeSlack()
    engine = VerificationEngine(UnreachableFakeKubernetes(), slack, wait_seconds=0.01, context_client=FakeContext())
    result = ActionResult(RemediationAction.COLLECT_LOGS, True, "log output", "api-abc123")

    outcome = await engine.verify(_incident(), "thread-1", result)

    assert outcome.status is VerificationStatus.SUCCESS
    assert "log output" in outcome.message


@pytest.mark.asyncio
async def test_report_failure_posts_message_and_returns_failed_result() -> None:
    slack = FakeSlack()
    engine = VerificationEngine(FakeKubernetes(), slack, wait_seconds=0.01, context_client=FakeContext())

    outcome = await engine.report_failure("thread-1")

    assert outcome.status is VerificationStatus.FAILED
    assert outcome.success is False
    assert len(slack.messages) == 1
