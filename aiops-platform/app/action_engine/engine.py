"""Executes approved remediation decisions through infrastructure connectors."""

from app.action_engine.kubernetes import KubernetesConnector
from app.connectors.github import GitHubConnector
from app.models.incident import Incident
from app.models.remediation import ActionResult, RemediationAction, RemediationDecision


class KubernetesActionEngine:
    """Translates remediation decisions into Kubernetes or GitHub operations."""

    def __init__(self, kubernetes: KubernetesConnector, github: GitHubConnector | None = None) -> None:
        self._kubernetes = kubernetes
        self._github = github

    async def execute(self, incident: Incident, decision: RemediationDecision, pod_name: str | None = None) -> ActionResult:
        """Execute the selected action and return an auditable result."""
        action = decision.action
        if action is RemediationAction.RESTART_POD:
            if not pod_name:
                return ActionResult(action, False, "A pod name is required to restart a pod.")
            await self._kubernetes.restart_pod(incident.namespace, pod_name)
            return ActionResult(action, True, "Pod deletion requested; its controller will recreate it.", pod_name)
        if action is RemediationAction.RESTART_DEPLOYMENT:
            await self._kubernetes.restart_deployment(incident.namespace, incident.service)
            return ActionResult(action, True, "Deployment rolling restart requested.", incident.service)
        if action is RemediationAction.SCALE_DEPLOYMENT:
            return ActionResult(action, False, "Scale actions require an explicit approved replica target.", incident.service)
        if action is RemediationAction.ROLLBACK_DEPLOYMENT:
            await self._kubernetes.rollback_deployment(incident.namespace, incident.service)
            return ActionResult(action, True, "Deployment rollback requested.", incident.service)
        if action is RemediationAction.DELETE_POD:
            if not pod_name:
                return ActionResult(action, False, "A pod name is required to delete a pod.")
            await self._kubernetes.delete_pod(incident.namespace, pod_name)
            return ActionResult(action, True, "Pod deletion requested.", pod_name)
        if action is RemediationAction.COLLECT_LOGS:
            if not pod_name:
                return ActionResult(action, False, "A pod name is required to collect logs.")
            logs = await self._kubernetes.collect_logs(incident.namespace, pod_name)
            return ActionResult(action, True, logs, pod_name)
        if action is RemediationAction.CREATE_GITHUB_PR:
            if self._github is None:
                return ActionResult(action, False, "GitHub integration is not configured.")
            body = f"# AIOps remediation plan\n\nIncident: `{incident.identifier}`\n\n{decision.reason}\n\nRoot cause: {decision.root_cause.category}\nEvidence: {decision.root_cause.evidence}\n"
            pull_request = await self._github.create_remediation_pull_request(f"aiops-{incident.identifier}", f"AIOps: remediate high memory for {incident.service}", body)
            return ActionResult(action, True, "Created remediation pull request.", pull_request_url=pull_request.url)
        return ActionResult(action, True, decision.reason)
