"""Orchestrates approved remediation decisions into allow-listed Kubernetes actions.

This engine never receives or executes raw text from Claude. A RemediationDecision
carries only a validated `RemediationAction` enum member (see app.ai.response_parser),
never a free-form command string, and every action is resolved against an explicit
allow-list before anything touches the cluster. Anything not on the allow-list is
rejected and reported back as a failed ActionResult -- it is never executed.
"""

from app.action_engine.kubernetes import ActionResult as KubernetesActionResult, KubernetesConnector
from app.connectors.github import GitHubConnector
from app.models.incident import Incident
from app.models.remediation import ActionResult, RemediationAction, RemediationDecision

_ALLOWED_ACTIONS: frozenset[str] = frozenset({
    "restart_pod", "restart_deployment", "scale_deployment", "describe_pod",
    "describe_node", "collect_logs", "collect_events", "patch_memory", "patch_cpu",
    "cordon_node", "drain_node", "delete_pod", "no_action",
})

_ACTION_ALIASES: dict[str, str] = {"rollout_restart": "restart_deployment"}


class KubernetesActionEngine:
    """Resolves a remediation decision against the allow-list and executes it."""

    def __init__(self, kubernetes: KubernetesConnector, github: GitHubConnector | None = None) -> None:
        self._kubernetes = kubernetes
        self._github = github  # retained for constructor compatibility; unused by the Kubernetes allow-list

    async def execute(
        self,
        incident: Incident,
        decision: RemediationDecision,
        pod_name: str | None = None,
        *,
        replicas: int | None = None,
        memory_limit: str | None = None,
        cpu_limit: str | None = None,
        node_name: str | None = None,
    ) -> ActionResult:
        """Execute the decision's action if and only if it is on the allow-list."""
        raw_action = decision.action.value
        action_name = _ACTION_ALIASES.get(raw_action, raw_action)
        if action_name not in _ALLOWED_ACTIONS:
            rejection = KubernetesActionResult(False, raw_action, f"Action '{raw_action}' is not on the Kubernetes action allow-list.", 0.0, {}, False)
            return self._to_remediation_result(decision.action, rejection)
        outcome = await self._dispatch(action_name, incident, decision, pod_name, replicas, memory_limit, cpu_limit, node_name)
        return self._to_remediation_result(decision.action, outcome)

    async def _dispatch(
        self,
        action_name: str,
        incident: Incident,
        decision: RemediationDecision,
        pod_name: str | None,
        replicas: int | None,
        memory_limit: str | None,
        cpu_limit: str | None,
        node_name: str | None,
    ) -> KubernetesActionResult:
        """Call the matching allow-listed Kubernetes helper method."""
        if action_name == "restart_pod":
            if not pod_name:
                return self._missing_param("restart_pod", "A pod name is required to restart a pod.")
            return await self._kubernetes.restart_pod(incident.namespace, pod_name)
        if action_name == "restart_deployment":
            return await self._kubernetes.restart_deployment(incident.namespace, incident.service)
        if action_name == "scale_deployment":
            if replicas is None:
                return self._missing_param("scale_deployment", "Scale actions require an explicit approved replica target.")
            return await self._kubernetes.scale_deployment(incident.namespace, incident.service, replicas)
        if action_name == "describe_pod":
            if not pod_name:
                return self._missing_param("describe_pod", "A pod name is required to describe a pod.")
            return await self._kubernetes.describe_pod(incident.namespace, pod_name)
        if action_name == "describe_node":
            if not node_name:
                return self._missing_param("describe_node", "A node name is required to describe a node.")
            return await self._kubernetes.describe_node(node_name)
        if action_name == "collect_logs":
            if not pod_name:
                return self._missing_param("collect_logs", "A pod name is required to collect logs.")
            return await self._kubernetes.collect_logs(incident.namespace, pod_name)
        if action_name == "collect_events":
            if not pod_name:
                return self._missing_param("collect_events", "A pod name is required to collect events.")
            return await self._kubernetes.collect_events(incident.namespace, pod_name)
        if action_name == "patch_memory":
            if memory_limit is None:
                return self._missing_param("patch_memory", "Patching memory requires an explicit approved memory limit.")
            return await self._kubernetes.patch_memory(incident.namespace, incident.service, memory_limit)
        if action_name == "patch_cpu":
            if cpu_limit is None:
                return self._missing_param("patch_cpu", "Patching CPU requires an explicit approved CPU limit.")
            return await self._kubernetes.patch_cpu(incident.namespace, incident.service, cpu_limit)
        if action_name == "cordon_node":
            if not node_name:
                return self._missing_param("cordon_node", "A node name is required to cordon a node.")
            return await self._kubernetes.cordon_node(node_name)
        if action_name == "drain_node":
            if not node_name:
                return self._missing_param("drain_node", "A node name is required to drain a node.")
            return await self._kubernetes.drain_node(node_name)
        if action_name == "delete_pod":
            if not pod_name:
                return self._missing_param("delete_pod", "A pod name is required to delete a pod.")
            return await self._kubernetes.delete_pod(incident.namespace, pod_name)
        return KubernetesActionResult(True, "no_action", decision.reason or "No remediation action required.", 0.0, {}, False)

    @staticmethod
    def _missing_param(action: str, message: str) -> KubernetesActionResult:
        """Build a rejected result for an allow-listed action missing a required parameter."""
        return KubernetesActionResult(False, action, message, 0.0, {}, False)

    @staticmethod
    def _to_remediation_result(action: RemediationAction, outcome: KubernetesActionResult) -> ActionResult:
        """Adapt the Kubernetes action engine's result into the shared pipeline contract."""
        resource_name = outcome.details.get("pod") or outcome.details.get("deployment") or outcome.details.get("node")
        return ActionResult(action, outcome.success, outcome.message, resource_name)
