"""GitHub pull-request automation for Claude-proposed YAML remediations.

Claude never talks to GitHub. It only returns a YAML patch and a description
in its schema-validated JSON response (see app.ai.response_parser); every
GitHub operation -- branch creation, commit, push, and pull request -- is
performed here, in Python, through the GitHub REST API via PyGithub. No git
binary or subprocess is used anywhere in this module.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SUPPORTED_KIND_FILENAMES: dict[str, str] = {
    "Deployment": "deployment.yaml",
    "StatefulSet": "statefulset.yaml",
    "DaemonSet": "daemonset.yaml",
    "Kustomization": "kustomization.yaml",
}
_DEFAULT_FILENAME = "values.yaml"
_BRANCH_PREFIX = "aiops/fix"


class GitHubAuthenticationError(RuntimeError):
    """Raised when GitHub rejects the configured credentials."""


class YAMLValidationError(ValueError):
    """Raised when a Claude-proposed YAML patch is not valid, supported YAML."""


@dataclass(frozen=True, slots=True)
class GitHubPRResult:
    """Structured outcome of a GitHub pull-request automation attempt."""

    success: bool
    url: str | None
    branch: str | None
    commit_sha: str | None
    file_path: str | None
    message: str


class GitHubAIConnector:
    """Applies a Claude-proposed YAML fix to a new branch and opens a pull request.

    Each step below is the REST-API equivalent of a local git operation, so the
    whole workflow -- clone, checkout base branch, create feature branch, apply
    patch, commit, push, open PR -- happens through typed GitHub API calls only:
    reading the base branch stands in for clone + checkout, `create_git_ref`
    creates (and implicitly pushes) the feature branch, and `create_file` /
    `update_file` both commit and push the change in a single call.
    """

    def __init__(self, token: str, repository: str, base_branch: str = "main") -> None:
        self._token = token
        self._repository = repository
        self._base_branch = base_branch

    def _repository_client(self) -> Any:
        """Authenticate with GitHub using the configured token and return the repo handle."""
        from github import Auth, Github
        return Github(auth=Auth.Token(self._token)).get_repo(self._repository)

    async def create_remediation_pull_request(
        self, incident_id: str, service: str, description: str, yaml_patch: str
    ) -> GitHubPRResult:
        """Validate, commit, and open a pull request for a Claude-proposed YAML fix.

        Never raises: YAML validation failures, authentication failures, and any
        other GitHub API error are all reported as a structured GitHubPRResult
        with success=False rather than propagating an exception.
        """
        try:
            document = self._validate_yaml(yaml_patch)
        except YAMLValidationError as exc:
            logger.warning("github_pr_rejected_invalid_yaml", extra={"incident_id": incident_id, "error": str(exc)})
            return GitHubPRResult(False, None, None, None, None, f"YAML validation failed: {exc}")

        file_path = self._resolve_file_path(service, document)
        branch = f"{_BRANCH_PREFIX}-{incident_id[:24]}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        clean_description = description.strip() or "automated remediation"
        title = f"AIOps: {clean_description[:72]}"
        body = self._pull_request_body(incident_id, service, clean_description, file_path)

        try:
            await self._create_branch(branch)
            commit_sha = await self._commit_file(branch, file_path, yaml_patch, f"fix: {clean_description}")
            pull_request_url = await self._open_pull_request(title, body, branch)
        except GitHubAuthenticationError as exc:
            logger.warning("github_pr_rejected_authentication_failure", extra={"incident_id": incident_id, "error": str(exc)})
            return GitHubPRResult(False, None, branch, None, file_path, f"GitHub authentication failed: {exc}")
        except Exception as exc:
            logger.exception("github_pr_creation_failed", extra={"incident_id": incident_id})
            return GitHubPRResult(False, None, branch, None, file_path, f"GitHub pull request creation failed: {exc}")

        return GitHubPRResult(True, pull_request_url, branch, commit_sha, file_path, "Pull request created successfully.")

    @staticmethod
    def _validate_yaml(yaml_patch: str | None) -> dict[str, Any]:
        """Parse and structurally validate a YAML patch before it is ever committed."""
        if not yaml_patch or not yaml_patch.strip():
            raise YAMLValidationError("yaml_patch is empty.")
        try:
            document = yaml.safe_load(yaml_patch)
        except yaml.YAMLError as exc:
            raise YAMLValidationError(f"malformed YAML: {exc}") from exc
        if not isinstance(document, dict):
            raise YAMLValidationError("YAML patch must decode to a mapping (a Kubernetes manifest or Helm values document).")
        return document

    @staticmethod
    def _resolve_file_path(service: str, document: dict[str, Any]) -> str:
        """Resolve the target file within the allow-listed set of supported manifests."""
        filename = _SUPPORTED_KIND_FILENAMES.get(document.get("kind"), _DEFAULT_FILENAME)
        safe_service = re.sub(r"[^a-zA-Z0-9_-]", "-", service) or "service"
        return f"k8s/{safe_service}/{filename}"

    @staticmethod
    def _pull_request_body(incident_id: str, service: str, description: str, file_path: str) -> str:
        """Render a review-friendly pull-request description."""
        return (
            "# AIOps automated remediation\n\n"
            f"Incident: `{incident_id}`\nService: `{service}`\nFile: `{file_path}`\n\n"
            f"## Proposed fix\n{description}\n\n"
            "_This pull request was generated automatically by Claude via the AIOps platform. "
            "Review and test before merging._"
        )

    async def _create_branch(self, branch: str) -> None:
        """Create a feature branch from the base branch (clone + checkout + branch, in one call)."""
        def operation() -> None:
            repo = self._repository_client()
            base = repo.get_branch(self._base_branch)
            repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base.commit.sha)
        await self._run(operation)

    async def _commit_file(self, branch: str, path: str, content: str, message: str) -> str:
        """Commit and push the YAML file to the feature branch; return the commit SHA."""
        def operation() -> str:
            repo = self._repository_client()
            try:
                existing = repo.get_contents(path, ref=branch)
                result = repo.update_file(path, message, content, existing.sha, branch=branch)
            except Exception as exc:
                if exc.__class__.__name__ != "UnknownObjectException":
                    raise
                result = repo.create_file(path, message, content, branch=branch)
            return result["commit"].sha
        return await self._run(operation)

    async def _open_pull_request(self, title: str, body: str, branch: str) -> str:
        """Open the pull request and return its URL."""
        def operation() -> str:
            pull_request = self._repository_client().create_pull(title=title, body=body, head=branch, base=self._base_branch)
            return pull_request.html_url
        return await self._run(operation)

    @staticmethod
    async def _run(operation: Any) -> Any:
        """Run a blocking PyGithub call off the event loop, raising a typed auth error on 401/403."""
        try:
            return await asyncio.to_thread(operation)
        except GitHubAuthenticationError:
            raise
        except Exception as exc:
            if exc.__class__.__name__ == "BadCredentialsException" or getattr(exc, "status", None) in (401, 403):
                raise GitHubAuthenticationError(str(exc)) from exc
            raise
