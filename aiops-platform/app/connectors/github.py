"""Asynchronous adapter for GitHub repository and pull-request operations."""

import asyncio
from dataclasses import dataclass


class GitHubIntegrationError(RuntimeError):
    """Raised when a GitHub API operation cannot be completed."""


@dataclass(frozen=True, slots=True)
class PullRequestResult:
    """Created pull-request metadata."""

    url: str
    number: int


class GitHubConnector:
    """Uses PyGithub through worker threads to avoid blocking the event loop."""

    def __init__(self, token: str, repository: str, base_branch: str = "main") -> None:
        self._token = token
        self._repository = repository
        self._base_branch = base_branch

    def _repository_client(self):
        from github import Auth, Github

        return Github(auth=Auth.Token(self._token)).get_repo(self._repository)

    async def create_branch(self, branch: str) -> None:
        """Create a branch from the configured base branch."""
        def operation() -> None:
            repo = self._repository_client()
            base = repo.get_branch(self._base_branch)
            repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base.commit.sha)
        await self._run(operation)

    async def commit_file(self, branch: str, path: str, content: str, message: str) -> None:
        """Create or update a UTF-8 file in a branch."""
        def operation() -> None:
            repo = self._repository_client()
            try:
                existing = repo.get_contents(path, ref=branch)
                repo.update_file(path, message, content, existing.sha, branch=branch)
            except Exception as exc:
                if exc.__class__.__name__ != "UnknownObjectException":
                    raise
                repo.create_file(path, message, content, branch=branch)
        await self._run(operation)

    async def create_pull_request(self, title: str, body: str, branch: str) -> PullRequestResult:
        """Open a pull request and return its URL."""
        def operation() -> PullRequestResult:
            pull_request = self._repository_client().create_pull(title=title, body=body, head=branch, base=self._base_branch)
            return PullRequestResult(url=pull_request.html_url, number=pull_request.number)
        return await self._run(operation)

    async def comment_on_pull_request(self, number: int, body: str) -> None:
        """Post a review-context comment on an existing pull request."""
        await self._run(lambda: self._repository_client().get_pull(number).create_issue_comment(body))

    async def create_remediation_pull_request(self, incident_id: str, title: str, body: str) -> PullRequestResult:
        """Create a tracked remediation report branch, commit, and pull request."""
        branch = f"aiops/remediation-{incident_id[:24]}"
        await self.create_branch(branch)
        path = f".aiops/remediations/{incident_id}.md"
        await self.commit_file(branch, path, body, f"docs: add remediation plan for {incident_id}")
        result = await self.create_pull_request(title, body, branch)
        await self.comment_on_pull_request(result.number, "Created automatically by aiops-platform; review before merging.")
        return result

    @staticmethod
    async def _run(operation):
        try:
            return await asyncio.to_thread(operation)
        except Exception as exc:
            raise GitHubIntegrationError("GitHub operation failed.") from exc
