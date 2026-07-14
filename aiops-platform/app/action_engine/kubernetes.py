"""Kubernetes operations implemented exclusively with the official Python client.

This module never shells out. It never uses `subprocess`, `kubectl`, `os.system`,
or `shell=True` -- every operation is a typed call through the Kubernetes Python
client library, so there is no way for a caller (including Claude-generated
text) to smuggle an arbitrary command into execution here.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_PROTECTED_NAMESPACES = frozenset({"kube-system", "kube-public", "kube-node-lease"})
_CONTROL_PLANE_NODE_LABELS = ("node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master")
_VERIFICATION_REQUIRED_ACTIONS = frozenset({
    "restart_pod", "restart_deployment", "scale_deployment", "patch_memory",
    "patch_cpu", "cordon_node", "drain_node", "delete_pod", "rollback_deployment",
})


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Structured outcome of a single Kubernetes action-engine operation."""

    success: bool
    action: str
    message: str
    execution_time: float
    details: dict[str, Any]
    verification_required: bool


class KubernetesConnector:
    """Provides non-blocking, allow-listed Kubernetes operations for the action engine."""

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
        self._core_api, self._apps_api = await asyncio.to_thread(load)

    # ------------------------------------------------------------------
    # Allow-listed action methods -- each always returns an ActionResult.
    # ------------------------------------------------------------------

    async def restart_pod(self, namespace: str, name: str) -> ActionResult:
        """Restart a managed pod by deleting it so its controller recreates it."""
        guard = self._guard_namespace("restart_pod", namespace)
        if guard is not None:
            return guard
        def op() -> dict[str, Any]:
            self._core_api.delete_namespaced_pod(name, namespace)
            return {"pod": name, "namespace": namespace}
        return await self._execute("restart_pod", namespace, name, op)

    async def restart_deployment(self, namespace: str, name: str) -> ActionResult:
        """Trigger a rolling restart by updating the pod-template restart annotation."""
        guard = self._guard_namespace("restart_deployment", namespace)
        if guard is not None:
            return guard
        def op() -> dict[str, Any]:
            from datetime import UTC, datetime
            body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(UTC).isoformat()}}}}}
            self._apps_api.patch_namespaced_deployment(name, namespace, body)
            return {"deployment": name, "namespace": namespace}
        return await self._execute("restart_deployment", namespace, name, op)

    async def scale_deployment(self, namespace: str, name: str, replicas: int) -> ActionResult:
        """Set a deployment replica count."""
        guard = self._guard_namespace("scale_deployment", namespace)
        if guard is not None:
            return guard
        if replicas < 0:
            return ActionResult(False, "scale_deployment", "Replica count cannot be negative.", 0.0, {"namespace": namespace, "deployment": name}, False)
        def op() -> dict[str, Any]:
            self._apps_api.patch_namespaced_deployment_scale(name, namespace, {"spec": {"replicas": replicas}})
            return {"deployment": name, "namespace": namespace, "replicas": replicas}
        return await self._execute("scale_deployment", namespace, name, op)

    async def rollback_deployment(self, namespace: str, name: str) -> ActionResult:
        """Rollback a deployment using the prior ReplicaSet pod template."""
        guard = self._guard_namespace("rollback_deployment", namespace)
        if guard is not None:
            return guard
        def op() -> dict[str, Any]:
            selector = f"app={name}"
            replica_sets = self._apps_api.list_namespaced_replica_set(namespace, label_selector=selector).items
            candidates = [item for item in replica_sets if item.spec.replicas and item.metadata.owner_references]
            if len(candidates) < 2:
                raise PermissionError("No previous ReplicaSet is available for rollback.")
            candidates.sort(key=lambda item: item.metadata.creation_timestamp, reverse=True)
            previous = candidates[1]
            self._apps_api.patch_namespaced_deployment(name, namespace, {"spec": {"template": previous.spec.template.to_dict()}})
            return {"deployment": name, "namespace": namespace}
        return await self._execute("rollback_deployment", namespace, name, op)

    async def delete_pod(self, namespace: str, name: str) -> ActionResult:
        """Delete a pod."""
        guard = self._guard_namespace("delete_pod", namespace)
        if guard is not None:
            return guard
        def op() -> dict[str, Any]:
            self._core_api.delete_namespaced_pod(name, namespace)
            return {"pod": name, "namespace": namespace}
        return await self._execute("delete_pod", namespace, name, op)

    async def describe_pod(self, namespace: str, name: str) -> ActionResult:
        """Return a human-readable summary of pod status, conditions, and container states."""
        def op() -> dict[str, Any]:
            pod = self._core_api.read_namespaced_pod(name, namespace)
            return {"description": self._format_pod_description(pod)}
        return await self._execute("describe_pod", namespace, name, op)

    async def describe_node(self, name: str) -> ActionResult:
        """Return a human-readable summary of node status, conditions, and capacity."""
        def op() -> dict[str, Any]:
            node = self._core_api.read_node(name)
            return {"description": self._format_node_description(node)}
        return await self._execute("describe_node", None, name, op)

    async def collect_logs(self, namespace: str, name: str, tail_lines: int = 200) -> ActionResult:
        """Collect recent pod logs for diagnosis."""
        def op() -> dict[str, Any]:
            logs = self._core_api.read_namespaced_pod_log(name, namespace, tail_lines=tail_lines, timestamps=True)
            return {"logs": logs}
        return await self._execute("collect_logs", namespace, name, op)

    async def collect_events(self, namespace: str, name: str) -> ActionResult:
        """Collect recent Kubernetes events associated with a pod for diagnosis."""
        def op() -> dict[str, Any]:
            field_selector = f"involvedObject.name={name}"
            events = self._core_api.list_namespaced_event(namespace, field_selector=field_selector)
            return {"events": [event.to_dict() for event in events.items]}
        return await self._execute("collect_events", namespace, name, op)

    async def patch_memory(self, namespace: str, name: str, limit: str, request: str | None = None) -> ActionResult:
        """Patch the memory limit (and optional request) of a deployment's primary container."""
        guard = self._guard_namespace("patch_memory", namespace)
        if guard is not None:
            return guard
        resources: dict[str, dict[str, str]] = {"limits": {"memory": limit}}
        if request:
            resources["requests"] = {"memory": request}
        return await self._patch_primary_container_resources("patch_memory", namespace, name, resources)

    async def patch_cpu(self, namespace: str, name: str, limit: str, request: str | None = None) -> ActionResult:
        """Patch the CPU limit (and optional request) of a deployment's primary container."""
        guard = self._guard_namespace("patch_cpu", namespace)
        if guard is not None:
            return guard
        resources: dict[str, dict[str, str]] = {"limits": {"cpu": limit}}
        if request:
            resources["requests"] = {"cpu": request}
        return await self._patch_primary_container_resources("patch_cpu", namespace, name, resources)

    async def cordon_node(self, name: str) -> ActionResult:
        """Mark a node unschedulable without evicting its existing pods."""
        def op() -> dict[str, Any]:
            node = self._core_api.read_node(name)
            self._reject_control_plane_node("cordon_node", name, node)
            self._core_api.patch_node(name, {"spec": {"unschedulable": True}})
            return {"node": name}
        return await self._execute("cordon_node", None, name, op)

    async def drain_node(self, name: str) -> ActionResult:
        """Cordon a node and remove its evictable, non-DaemonSet pods for maintenance."""
        def op() -> dict[str, Any]:
            node = self._core_api.read_node(name)
            self._reject_control_plane_node("drain_node", name, node)
            self._core_api.patch_node(name, {"spec": {"unschedulable": True}})
            field_selector = f"spec.nodeName={name},status.phase!=Succeeded,status.phase!=Failed"
            pods = self._core_api.list_pod_for_all_namespaces(field_selector=field_selector).items
            evicted = []
            for pod in pods:
                owners = pod.metadata.owner_references or []
                if any(owner.kind == "DaemonSet" for owner in owners):
                    continue
                self._core_api.delete_namespaced_pod(pod.metadata.name, pod.metadata.namespace)
                evicted.append(pod.metadata.name)
            return {"node": name, "evicted_pods": evicted}
        return await self._execute("drain_node", None, name, op)

    # ------------------------------------------------------------------
    # Read-only helpers used by the verification engine (unchanged contract).
    # ------------------------------------------------------------------

    async def deployment_healthy(self, namespace: str, name: str) -> bool:
        """Return whether a deployment has all desired replicas available."""
        await self._initialize()
        deployment = await asyncio.to_thread(lambda: self._apps_api.read_namespaced_deployment_status(name, namespace))
        desired = deployment.spec.replicas or 0
        return (deployment.status.available_replicas or 0) >= desired and (deployment.status.updated_replicas or 0) >= desired

    async def deployment_status(self, namespace: str, name: str) -> dict[str, int]:
        """Return desired, available, and updated replica counts for convergence checks."""
        await self._initialize()
        deployment = await asyncio.to_thread(lambda: self._apps_api.read_namespaced_deployment_status(name, namespace))
        return {
            "desired": deployment.spec.replicas or 0,
            "available": deployment.status.available_replicas or 0,
            "updated": deployment.status.updated_replicas or 0,
        }

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    async def _patch_primary_container_resources(self, action: str, namespace: str, name: str, resources: dict[str, dict[str, str]]) -> ActionResult:
        def op() -> dict[str, Any]:
            deployment = self._apps_api.read_namespaced_deployment(name, namespace)
            containers = deployment.spec.template.spec.containers
            if not containers:
                raise PermissionError(f"Deployment '{name}' has no containers to patch.")
            container_name = containers[0].name
            body = {"spec": {"template": {"spec": {"containers": [{"name": container_name, "resources": resources}]}}}}
            self._apps_api.patch_namespaced_deployment(name, namespace, body)
            return {"deployment": name, "namespace": namespace, "resources": resources}
        return await self._execute(action, namespace, name, op)

    @staticmethod
    def _guard_namespace(action: str, namespace: str) -> ActionResult | None:
        """Refuse mutating actions targeting protected system namespaces."""
        if namespace in _PROTECTED_NAMESPACES:
            logger.warning("action_rejected_protected_namespace", extra={"action": action, "namespace": namespace})
            return ActionResult(
                False, action, f"Refusing to run '{action}' in protected namespace '{namespace}'.",
                0.0, {"namespace": namespace}, False,
            )
        return None

    @staticmethod
    def _reject_control_plane_node(action: str, name: str, node: Any) -> None:
        """Raise if a node-level action targets a control-plane node."""
        labels = node.metadata.labels or {}
        if any(label in labels for label in _CONTROL_PLANE_NODE_LABELS):
            raise PermissionError(f"Refusing to run '{action}' on control-plane node '{name}'.")

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
    def _format_node_description(node: Any) -> str:
        """Render a compact, human-readable summary of node status and capacity."""
        lines = [f"Node: {node.metadata.name}", f"Unschedulable: {bool(node.spec.unschedulable)}"]
        for condition in node.status.conditions or []:
            lines.append(f"Condition: {condition.type}={condition.status} ({condition.reason or 'n/a'})")
        capacity = node.status.capacity or {}
        allocatable = node.status.allocatable or {}
        lines.append(f"Capacity: cpu={capacity.get('cpu')} memory={capacity.get('memory')} pods={capacity.get('pods')}")
        lines.append(f"Allocatable: cpu={allocatable.get('cpu')} memory={allocatable.get('memory')} pods={allocatable.get('pods')}")
        return "\n".join(lines)

    async def _execute(self, action: str, namespace: str | None, resource: str | None, operation: Any) -> ActionResult:
        """Run one Kubernetes operation off the event loop; never raise, always log."""
        from kubernetes.client.exceptions import ApiException
        started = time.perf_counter()
        try:
            await self._initialize()
            details = await asyncio.to_thread(operation)
        except PermissionError as exc:
            elapsed = round(time.perf_counter() - started, 3)
            self._log(action, namespace, resource, elapsed, False)
            return ActionResult(False, action, str(exc), elapsed, {}, False)
        except ApiException as exc:
            elapsed = round(time.perf_counter() - started, 3)
            self._log(action, namespace, resource, elapsed, False)
            message = f"Kubernetes API error while running '{action}': {exc.reason or exc.status}"
            return ActionResult(False, action, message, elapsed, {"status_code": exc.status}, False)
        except Exception as exc:
            elapsed = round(time.perf_counter() - started, 3)
            self._log(action, namespace, resource, elapsed, False)
            return ActionResult(False, action, f"Kubernetes operation '{action}' failed: {exc}", elapsed, {}, False)
        elapsed = round(time.perf_counter() - started, 3)
        self._log(action, namespace, resource, elapsed, True)
        payload = details if isinstance(details, dict) else {"result": details}
        return ActionResult(True, action, f"'{action}' completed successfully.", elapsed, payload, action in _VERIFICATION_REQUIRED_ACTIONS)

    @staticmethod
    def _log(action: str, namespace: str | None, resource: str | None, execution_time: float, success: bool) -> None:
        """Emit structured operational metadata for every Kubernetes action attempt."""
        logger.info(
            "kubernetes_action_completed",
            extra={"action": action, "namespace": namespace, "resource": resource, "execution_time": execution_time, "success": success},
        )
