"""Unit tests for the Kubernetes action engine and its allow-list."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.action_engine.engine import KubernetesActionEngine
from app.action_engine.kubernetes import ActionResult, KubernetesConnector
from app.models.incident import Incident, IncidentSeverity
from app.models.remediation import RemediationAction, RemediationDecision, RootCause


def _incident(namespace: str = "prod") -> Incident:
    return Incident("1", "CrashLoopBackOff", IncidentSeverity.CRITICAL, namespace, "payment-api", "cluster", datetime.now(UTC), "summary")


def _decision(action: RemediationAction) -> RemediationDecision:
    root_cause = RootCause("CrashLoopBackOff", 0.98, "evidence", action)
    return RemediationDecision(action, "reason", root_cause)


def _connector_with_mocked_client() -> KubernetesConnector:
    connector = KubernetesConnector()
    connector._core_api = MagicMock()
    connector._apps_api = MagicMock()
    return connector


@pytest.mark.asyncio
async def test_restart_pod_executes_through_kubernetes_client() -> None:
    connector = _connector_with_mocked_client()
    engine = KubernetesActionEngine(connector)
    incident = _incident()
    decision = _decision(RemediationAction.RESTART_POD)

    result = await engine.execute(incident, decision, pod_name="payment-api-abc123")

    assert result.succeeded is True
    assert result.action is RemediationAction.RESTART_POD
    connector._core_api.delete_namespaced_pod.assert_called_once_with("payment-api-abc123", "prod")


@pytest.mark.asyncio
async def test_restart_deployment_executes_through_kubernetes_client() -> None:
    connector = _connector_with_mocked_client()
    engine = KubernetesActionEngine(connector)
    incident = _incident()
    decision = _decision(RemediationAction.RESTART_DEPLOYMENT)

    result = await engine.execute(incident, decision)

    assert result.succeeded is True
    assert result.action is RemediationAction.RESTART_DEPLOYMENT
    connector._apps_api.patch_namespaced_deployment.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_action_is_rejected_without_touching_the_cluster() -> None:
    connector = _connector_with_mocked_client()
    engine = KubernetesActionEngine(connector)
    incident = _incident()
    decision = _decision(RemediationAction.CREATE_GITHUB_PR)

    result = await engine.execute(incident, decision)

    assert result.succeeded is False
    assert "not on the Kubernetes action allow-list" in result.detail
    assert connector._core_api.method_calls == []
    assert connector._apps_api.method_calls == []


@pytest.mark.asyncio
async def test_protected_namespace_is_refused() -> None:
    connector = _connector_with_mocked_client()
    engine = KubernetesActionEngine(connector)
    incident = _incident(namespace="kube-system")
    decision = _decision(RemediationAction.RESTART_POD)

    result = await engine.execute(incident, decision, pod_name="coredns-abc")

    assert result.succeeded is False
    assert "protected namespace" in result.detail
    connector._core_api.delete_namespaced_pod.assert_not_called()


@pytest.mark.asyncio
async def test_missing_required_parameter_is_rejected() -> None:
    connector = _connector_with_mocked_client()
    engine = KubernetesActionEngine(connector)
    incident = _incident()
    decision = _decision(RemediationAction.RESTART_POD)

    result = await engine.execute(incident, decision, pod_name=None)

    assert result.succeeded is False
    assert "pod name is required" in result.detail
    connector._core_api.delete_namespaced_pod.assert_not_called()


def test_kubernetes_action_result_structure() -> None:
    result = ActionResult(True, "restart_pod", "ok", 0.123, {"pod": "x"}, True)

    assert result.success is True
    assert result.action == "restart_pod"
    assert result.message == "ok"
    assert result.execution_time == 0.123
    assert result.details == {"pod": "x"}
    assert result.verification_required is True
