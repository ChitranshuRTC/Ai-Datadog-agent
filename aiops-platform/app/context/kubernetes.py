"""Async, read-only Kubernetes context helpers backed by the official Python client."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class KubernetesContextClient:
    """Provides best-effort, non-blocking Kubernetes reads for incident context collection.

    Every method degrades to a placeholder value instead of raising when cluster
    configuration is unavailable, since context collection must never interrupt
    the webhook or Slack notification flow.
    """

    def __init__(self, in_cluster: bool = False) -> None:
        self._in_cluster = in_cluster
        self._core_api: Any | None = None
        self._apps_api: Any | None = None
        self._available = True

    async def _initialize(self) -> bool:
        """Load Kubernetes client configuration once, remembering failure to avoid retries."""
        if self._core_api is not None or not self._available:
            return self._available
        def load() -> tuple[Any, Any]:
            from kubernetes import client, config
            if self._in_cluster:
                config.load_incluster_config()
            else:
                config.load_kube_config()
            return client.CoreV1Api(), client.AppsV1Api()
        try:
            self._core_api, self._apps_api = await asyncio.to_thread(load)
        except Exception:
            logger.warning("Kubernetes cluster configuration is unavailable; context collection will return placeholders.")
            self._available = False
        return self._available

    async def get_logs(self, namespace: str, pod: str, tail_lines: int = 200) -> str:
        """Return recent pod logs, or an empty string if the cluster is unreachable."""
        if not await self._initialize():
            return ""
        return await self._safe(
            lambda: self._core_api.read_namespaced_pod_log(pod, namespace, tail_lines=tail_lines, timestamps=True), ""
        )

    async def describe_pod(self, namespace: str, pod: str) -> str:
        """Return a human-readable pod summary, or an empty string if unavailable."""
        if not await self._initialize():
            return ""
        pod_manifest = await self._safe(lambda: self._core_api.read_namespaced_pod(pod, namespace), None)
        return self._format_pod_description(pod_manifest) if pod_manifest is not None else ""

    async def get_events(self, namespace: str, pod: str) -> list[dict[str, Any]]:
        """Return events involving a pod, or an empty list if unavailable."""
        if not await self._initialize():
            return []
        field_selector = f"involvedObject.name={pod}"
        events = await self._safe(
            lambda: self._core_api.list_namespaced_event(namespace, field_selector=field_selector), None
        )
        return [event.to_dict() for event in events.items] if events is not None else []

    async def get_deployment(self, namespace: str, name: str) -> dict[str, Any]:
        """Return a deployment manifest, or an empty mapping if unavailable."""
        if not await self._initialize():
            return {}
        deployment = await self._safe(lambda: self._apps_api.read_namespaced_deployment(name, namespace), None)
        return deployment.to_dict() if deployment is not None else {}

    async def get_replicasets(self, namespace: str, label_selector: str) -> list[dict[str, Any]]:
        """Return replica sets matching a label selector, or an empty list if unavailable."""
        if not await self._initialize():
            return []
        replica_sets = await self._safe(
            lambda: self._apps_api.list_namespaced_replica_set(namespace, label_selector=label_selector), None
        )
        return [item.to_dict() for item in replica_sets.items] if replica_sets is not None else []

    async def get_node(self, name: str) -> dict[str, Any]:
        """Return a node manifest, or an empty mapping if unavailable."""
        if not await self._initialize():
            return {}
        node = await self._safe(lambda: self._core_api.read_node(name), None)
        return node.to_dict() if node is not None else {}

    async def get_namespace(self, name: str) -> dict[str, Any]:
        """Return a namespace manifest, or an empty mapping if unavailable."""
        if not await self._initialize():
            return {}
        namespace = await self._safe(lambda: self._core_api.read_namespace(name), None)
        return namespace.to_dict() if namespace is not None else {}

    async def get_container_statuses(self, namespace: str, pod: str) -> list[dict[str, Any]]:
        """Return per-container status entries for a pod, or an empty list if unavailable."""
        if not await self._initialize():
            return []
        pod_manifest = await self._safe(lambda: self._core_api.read_namespaced_pod(pod, namespace), None)
        if pod_manifest is None or not pod_manifest.status.container_statuses:
            return []
        return [status.to_dict() for status in pod_manifest.status.container_statuses]

    async def get_restart_count(self, namespace: str, pod: str) -> int:
        """Return the total container restart count for a pod, or zero if unavailable."""
        statuses = await self.get_container_statuses(namespace, pod)
        return sum(status.get("restart_count", 0) or 0 for status in statuses)

    async def get_pod_status(self, namespace: str, pod: str) -> dict[str, Any]:
        """Return a structured phase/readiness/restart summary for verification checks."""
        placeholder = {"phase": "Unknown", "ready": False, "restart_count": 0, "crash_loop_back_off": False, "waiting_reason": None}
        if not await self._initialize():
            return placeholder
        pod_manifest = await self._safe(lambda: self._core_api.read_namespaced_pod(pod, namespace), None)
        if pod_manifest is None:
            return placeholder
        conditions = pod_manifest.status.conditions or []
        ready = any(condition.type == "Ready" and condition.status == "True" for condition in conditions)
        container_statuses = pod_manifest.status.container_statuses or []
        restart_count = sum(status.restart_count or 0 for status in container_statuses)
        waiting_reasons = [
            status.state.waiting.reason
            for status in container_statuses
            if status.state and status.state.waiting and status.state.waiting.reason
        ]
        return {
            "phase": pod_manifest.status.phase or "Unknown",
            "ready": ready,
            "restart_count": restart_count,
            "crash_loop_back_off": "CrashLoopBackOff" in waiting_reasons,
            "waiting_reason": waiting_reasons[0] if waiting_reasons else None,
        }

    @staticmethod
    def _format_pod_description(pod: Any) -> str:
        """Render a compact, human-readable summary of pod status and conditions."""
        lines = [f"Pod: {pod.metadata.name}", f"Namespace: {pod.metadata.namespace}", f"Phase: {pod.status.phase}", f"Node: {pod.spec.node_name}"]
        for condition in pod.status.conditions or []:
            lines.append(f"Condition: {condition.type}={condition.status} ({condition.reason or 'n/a'})")
        for container_status in pod.status.container_statuses or []:
            state = container_status.state
            if state.running:
                state_name, reason = "running", ""
            elif state.waiting:
                state_name, reason = "waiting", state.waiting.reason or ""
            elif state.terminated:
                state_name, reason = "terminated", state.terminated.reason or ""
            else:
                state_name, reason = "unknown", ""
            lines.append(f"Container {container_status.name}: {state_name} restarts={container_status.restart_count} {reason}".strip())
        return "\n".join(lines)

    @staticmethod
    async def _safe(operation: Any, placeholder: Any) -> Any:
        """Run a blocking Kubernetes client call off the event loop, swallowing failures."""
        try:
            return await asyncio.to_thread(operation)
        except Exception:
            logger.warning("Kubernetes context operation failed; returning placeholder.", exc_info=True)
            return placeholder
