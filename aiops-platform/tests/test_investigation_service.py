"""Unit tests for Kubernetes evidence orchestration."""

import pytest

from app.models.investigation import InvestigationRequest
from app.services.investigation_service import InvestigationService


class FakeKubernetesInvestigator:
    """Connector test double providing deterministic cluster evidence."""

    async def get_pod(self, namespace: str, pod: str) -> dict:
        return {"metadata": {"name": pod, "labels": {"app": "api"}}, "spec": {"nodeName": "node-1"}, "status": {"phase": "Running", "containerStatuses": [{"name": "api", "restartCount": 2, "state": {"running": {}}}]}}

    async def describe_pod(self, namespace: str, pod: str) -> str:
        return "Pod description"

    async def get_logs(self, namespace: str, pod: str, tail_lines: int = 200) -> str:
        return "application log"

    async def get_events(self, namespace: str, pod: str) -> dict:
        return {"items": [{"reason": "BackOff", "message": "restarting", "type": "Warning", "count": 2}]}

    async def get_deployment(self, namespace: str, deployment: str) -> dict:
        return {"metadata": {"name": deployment}, "spec": {"replicas": 2}, "status": {"availableReplicas": 2, "updatedReplicas": 2}}


@pytest.mark.asyncio
async def test_investigation_collects_kubernetes_evidence() -> None:
    result = await InvestigationService(FakeKubernetesInvestigator()).investigate(InvestigationRequest(namespace="default", pod="api-1"))

    assert result.status == "Running"
    assert result.restart_count == 2
    assert result.deployment is not None and result.deployment.name == "api"
    assert result.events[0].reason == "BackOff"
