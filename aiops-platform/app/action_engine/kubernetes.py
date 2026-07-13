"""Async Kubernetes actions implemented with the official Python client."""

import asyncio
from typing import Any


class KubernetesActionError(RuntimeError):
    """Raised when a Kubernetes operation fails."""


class KubernetesConnector:
    """Provides non-blocking wrappers for Kubernetes workload operations."""

    def __init__(self, in_cluster: bool = False) -> None:
        self._in_cluster = in_cluster
        self._core_api: Any | None = None
        self._apps_api: Any | None = None

    async def _initialize(self) -> None:
        if self._core_api is not None:
            return
        def load() -> tuple[Any, Any]:
            from kubernetes import client, config
            if self._in_cluster:
                config.load_incluster_config()
            else:
                config.load_kube_config()
            return client.CoreV1Api(), client.AppsV1Api()
        self._core_api, self._apps_api = await self._run(load)

    async def restart_deployment(self, namespace: str, name: str) -> None:
        """Trigger a rolling restart by updating the pod-template restart annotation."""
        from datetime import UTC, datetime
        await self._initialize()
        body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(UTC).isoformat()}}}}}
        await self._run(lambda: self._apps_api.patch_namespaced_deployment(name, namespace, body))

    async def restart_pod(self, namespace: str, name: str) -> None:
        """Restart a managed pod by deleting it and allowing its controller to recreate it."""
        await self.delete_pod(namespace, name)

    async def scale_deployment(self, namespace: str, name: str, replicas: int) -> None:
        """Set a deployment replica count."""
        if replicas < 0:
            raise KubernetesActionError("Replica count cannot be negative.")
        await self._initialize()
        await self._run(lambda: self._apps_api.patch_namespaced_deployment_scale(name, namespace, {"spec": {"replicas": replicas}}))

    async def rollback_deployment(self, namespace: str, name: str) -> None:
        """Rollback using the prior ReplicaSet pod template."""
        await self._initialize()
        def rollback() -> None:
            selector = f"app={name}"
            replica_sets = self._apps_api.list_namespaced_replica_set(namespace, label_selector=selector).items
            candidates = [item for item in replica_sets if item.spec.replicas and item.metadata.owner_references]
            if len(candidates) < 2:
                raise KubernetesActionError("No previous ReplicaSet is available for rollback.")
            candidates.sort(key=lambda item: item.metadata.creation_timestamp, reverse=True)
            previous = candidates[1]
            self._apps_api.patch_namespaced_deployment(name, namespace, {"spec": {"template": previous.spec.template.to_dict()}})
        await self._run(rollback)

    async def delete_pod(self, namespace: str, name: str) -> None:
        """Delete a pod."""
        await self._initialize()
        await self._run(lambda: self._core_api.delete_namespaced_pod(name, namespace))

    async def collect_logs(self, namespace: str, pod_name: str, tail_lines: int = 200) -> str:
        """Collect recent pod logs for diagnosis."""
        await self._initialize()
        return await self._run(lambda: self._core_api.read_namespaced_pod_log(pod_name, namespace, tail_lines=tail_lines, timestamps=True))

    async def deployment_healthy(self, namespace: str, name: str) -> bool:
        """Return whether a deployment has all desired replicas available."""
        await self._initialize()
        deployment = await self._run(lambda: self._apps_api.read_namespaced_deployment_status(name, namespace))
        desired = deployment.spec.replicas or 0
        return (deployment.status.available_replicas or 0) >= desired and (deployment.status.updated_replicas or 0) >= desired

    @staticmethod
    async def _run(operation):
        try:
            return await asyncio.to_thread(operation)
        except KubernetesActionError:
            raise
        except Exception as exc:
            raise KubernetesActionError("Kubernetes operation failed.") from exc
