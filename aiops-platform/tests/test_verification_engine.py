"""Tests for post-action remediation verification updates."""

from datetime import UTC, datetime

import pytest

from app.models.incident import Incident, IncidentSeverity
from app.models.remediation import ActionResult, RemediationAction
from app.verification.engine import VerificationEngine


class FakeKubernetes:
    async def deployment_healthy(self, namespace: str, name: str) -> bool:
        return True


class FakeSlack:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def post_thread_update(self, thread_id: str, text: str) -> None:
        self.messages.append(text)


@pytest.mark.asyncio
async def test_verification_posts_successful_health_update() -> None:
    slack = FakeSlack()
    engine = VerificationEngine(FakeKubernetes(), slack, wait_seconds=0)
    incident = Incident("1", "Alert", IncidentSeverity.CRITICAL, "ns", "api", "cluster", datetime.now(UTC), "summary")
    result = ActionResult(RemediationAction.RESTART_DEPLOYMENT, True, "Restarted", "api")

    assert await engine.verify(incident, "thread-1", result)
    assert slack.messages == ["✅ Remediation verified: deployment is healthy."]
