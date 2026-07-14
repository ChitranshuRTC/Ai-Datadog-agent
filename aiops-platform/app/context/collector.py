"""Aggregates a best-effort Kubernetes diagnostic snapshot for an incident."""

from dataclasses import dataclass
from typing import Any

from app.context.kubernetes import KubernetesContextClient


@dataclass(frozen=True, slots=True)
class IncidentContext:
    """A point-in-time Kubernetes diagnostic snapshot gathered for one incident."""

    logs: str
    describe: str
    events: list[dict[str, Any]]
    deployment: dict[str, Any]
    replicaset: list[dict[str, Any]]
    node: dict[str, Any]
    namespace: dict[str, Any]
    container_status: list[dict[str, Any]]
    restart_count: int


class ContextCollector:
    """Collects diagnostic context for an incident, ready for future analysis stages."""

    def __init__(self, kubernetes: KubernetesContextClient) -> None:
        self._kubernetes = kubernetes

    async def collect_context(
        self,
        namespace: str,
        pod_name: str,
        deployment_name: str,
        node_name: str | None = None,
    ) -> IncidentContext:
        """Gather logs, diagnostics, and workload state for one namespace/pod/deployment."""
        label_selector = f"app={deployment_name}"
        return IncidentContext(
            logs=await self._kubernetes.get_logs(namespace, pod_name),
            describe=await self._kubernetes.describe_pod(namespace, pod_name),
            events=await self._kubernetes.get_events(namespace, pod_name),
            deployment=await self._kubernetes.get_deployment(namespace, deployment_name),
            replicaset=await self._kubernetes.get_replicasets(namespace, label_selector),
            node=await self._kubernetes.get_node(node_name) if node_name else {},
            namespace=await self._kubernetes.get_namespace(namespace),
            container_status=await self._kubernetes.get_container_statuses(namespace, pod_name),
            restart_count=await self._kubernetes.get_restart_count(namespace, pod_name),
        )
