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

    async def deployment_status(self, namespace: str, name: str) -> dict[str, int]:
        """Return desired, available, and updated replica counts for convergence checks."""
        await self._initialize()
        deployment = await self._run(lambda: self._apps_api.read_namespaced_deployment_status(name, namespace))
        return {
            "desired": deployment.spec.replicas or 0,
            "available": deployment.status.available_replicas or 0,
            "updated": deployment.status.updated_replicas or 0,
        }

    async def patch_memory(self, namespace: str, name: str, limit: str, request: str | None = None) -> None:
        """Patch the memory limit (and optional request) of a deployment's primary container."""
        resources: dict[str, dict[str, str]] = {"limits": {"memory": limit}}
        if request:
            resources["requests"] = {"memory": request}
        await self._patch_primary_container_resources(namespace, name, resources)

    async def patch_cpu(self, namespace: str, name: str, limit: str, request: str | None = None) -> None:
        """Patch the CPU limit (and optional request) of a deployment's primary container."""
        resources: dict[str, dict[str, str]] = {"limits": {"cpu": limit}}
        if request:
            resources["requests"] = {"cpu": request}
        await self._patch_primary_container_resources(namespace, name, resources)

    async def _patch_primary_container_resources(self, namespace: str, name: str, resources: dict[str, dict[str, str]]) -> None:
        await self._initialize()
        def patch() -> None:
            deployment = self._apps_api.read_namespaced_deployment(name, namespace)
            containers = deployment.spec.template.spec.containers
            if not containers:
                raise KubernetesActionError(f"Deployment {name} has no containers to patch.")
            container_name = containers[0].name
            body = {"spec": {"template": {"spec": {"containers": [{"name": container_name, "resources": resources}]}}}}
            self._apps_api.patch_namespaced_deployment(name, namespace, body)
        await self._run(patch)

    async def describe_pod(self, namespace: str, name: str) -> str:
        """Return a human-readable summary of pod status, conditions, and container states."""
        await self._initialize()
        pod = await self._run(lambda: self._core_api.read_namespaced_pod(name, namespace))
        return self._format_pod_description(pod)

    @staticmethod
    def _format_pod_description(pod: Any) -> str:
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

    async def collect_events(self, namespace: str, name: str) -> str:
        """Collect recent Kubernetes events associated with a pod for diagnosis."""
        await self._initialize()
        field_selector = f"involvedObject.name={name}"
        events = await self._run(lambda: self._core_api.list_namespaced_event(namespace, field_selector=field_selector))
        if not events.items:
            return f"No events found for pod {name} in namespace {namespace}."
        lines = [f"{event.last_timestamp or event.event_time}: {event.type}/{event.reason} - {event.message}" for event in events.items]
        return "\n".join(lines)

    async def cordon_node(self, name: str) -> None:
        """Mark a node unschedulable without evicting its existing pods."""
        await self._initialize()
        body = {"spec": {"unschedulable": True}}
        await self._run(lambda: self._core_api.patch_node(name, body))

    async def drain_node(self, name: str) -> None:
        """Cordon a node and remove its evictable, non-DaemonSet pods for maintenance."""
        await self.cordon_node(name)
        def drain() -> None:
            field_selector = f"spec.nodeName={name},status.phase!=Succeeded,status.phase!=Failed"
            pods = self._core_api.list_pod_for_all_namespaces(field_selector=field_selector).items
            for pod in pods:
                owners = pod.metadata.owner_references or []
                if any(owner.kind == "DaemonSet" for owner in owners):
                    continue
                self._core_api.delete_namespaced_pod(pod.metadata.name, pod.metadata.namespace)
        await self._run(drain)

    @staticmethod
    async def _run(operation):
        try:
            return await asyncio.to_thread(operation)
        except KubernetesActionError:
            raise
        except Exception as exc:
            raise KubernetesActionError("Kubernetes operation failed.") from exc
