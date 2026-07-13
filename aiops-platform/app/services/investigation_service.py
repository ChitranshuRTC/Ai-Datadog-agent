"""Application service that gathers Kubernetes evidence for a pod incident."""

import asyncio
from typing import Any, Protocol

from app.connectors.exceptions import ResourceNotFound
from app.models.investigation import DeploymentSummary, EventSummary, InvestigationRequest, InvestigationResult, PodSummary


class KubernetesInvestigator(Protocol):
    """Port exposing only the connector operations used by investigation."""

    async def get_pod(self, namespace: str, pod: str) -> dict[str, Any]: ...
    async def describe_pod(self, namespace: str, pod: str) -> str: ...
    async def get_logs(self, namespace: str, pod: str, tail_lines: int = 200) -> str: ...
    async def get_events(self, namespace: str, pod: str) -> dict[str, Any]: ...
    async def get_deployment(self, namespace: str, deployment: str) -> dict[str, Any]: ...


class InvestigationService:
    """Orchestrates Kubernetes collection without calling Slack, Datadog, or AI."""

    def __init__(self, connector: KubernetesInvestigator) -> None:
        """Accept the Kubernetes port to keep orchestration independently testable."""
        self._connector = connector

    async def investigate(self, request: InvestigationRequest) -> InvestigationResult:
        """Collect pod evidence and shape it into one typed investigation result."""
        pod_json = await self._connector.get_pod(request.namespace, request.pod)
        describe, logs, events_json = await asyncio.gather(
            self._connector.describe_pod(request.namespace, request.pod),
            self._connector.get_logs(request.namespace, request.pod),
            self._connector.get_events(request.namespace, request.pod),
        )
        deployment = await self._fetch_deployment(request.namespace, pod_json)
        return InvestigationResult(
            namespace=request.namespace,
            pod=self._pod_summary(pod_json, request.pod),
            deployment=deployment,
            status=self._pod_phase(pod_json),
            restart_count=self._restart_count(pod_json),
            container_status=self._container_status(pod_json),
            logs=logs,
            events=self._event_summaries(events_json),
            describe=describe,
            recommendation="Kubernetes evidence collected; submit this result to the AI analysis layer.",
        )

    async def _fetch_deployment(self, namespace: str, pod_json: dict[str, Any]) -> DeploymentSummary | None:
        """Fetch a deployment when a conventional workload label identifies one."""
        name = self._deployment_name(pod_json)
        if name is None:
            return None
        try:
            return self._deployment_summary(await self._connector.get_deployment(namespace, name))
        except ResourceNotFound:
            return None

    @staticmethod
    def _pod_summary(payload: dict[str, Any], fallback_name: str) -> PodSummary:
        """Extract stable pod metadata from kubectl JSON."""
        metadata = payload.get("metadata", {})
        spec = payload.get("spec", {})
        labels = {str(key): str(value) for key, value in metadata.get("labels", {}).items()}
        return PodSummary(name=str(metadata.get("name", fallback_name)), phase=InvestigationService._pod_phase(payload), node_name=spec.get("nodeName"), labels=labels)

    @staticmethod
    def _pod_phase(payload: dict[str, Any]) -> str:
        """Return Kubernetes pod phase with an explicit fallback."""
        return str(payload.get("status", {}).get("phase", "Unknown"))

    @staticmethod
    def _restart_count(payload: dict[str, Any]) -> int:
        """Sum restarts from all container statuses."""
        statuses = payload.get("status", {}).get("containerStatuses", [])
        return sum(int(status.get("restartCount", 0)) for status in statuses if isinstance(status, dict))

    @staticmethod
    def _container_status(payload: dict[str, Any]) -> dict[str, str]:
        """Create a concise container-name to state mapping."""
        statuses = payload.get("status", {}).get("containerStatuses", [])
        return {str(item.get("name", "unknown")): next(iter(item.get("state", {"Unknown": {}})), "Unknown") for item in statuses if isinstance(item, dict)}

    @staticmethod
    def _event_summaries(payload: dict[str, Any]) -> list[EventSummary]:
        """Convert event-list JSON into concise, serializable summaries."""
        return [EventSummary(reason=str(item.get("reason", "Unknown")), message=str(item.get("message", "")), event_type=str(item.get("type", "Normal")), count=int(item.get("count", 0))) for item in payload.get("items", []) if isinstance(item, dict)]

    @staticmethod
    def _deployment_name(payload: dict[str, Any]) -> str | None:
        """Infer a deployment name from standard Kubernetes workload labels."""
        labels = payload.get("metadata", {}).get("labels", {})
        return labels.get("app.kubernetes.io/name") or labels.get("app")

    @staticmethod
    def _deployment_summary(payload: dict[str, Any]) -> DeploymentSummary:
        """Extract rollout replica counts from a deployment manifest."""
        spec, status, metadata = payload.get("spec", {}), payload.get("status", {}), payload.get("metadata", {})
        return DeploymentSummary(name=str(metadata.get("name", "unknown")), desired_replicas=int(spec.get("replicas", 0)), available_replicas=int(status.get("availableReplicas", 0)), updated_replicas=int(status.get("updatedReplicas", 0)))
