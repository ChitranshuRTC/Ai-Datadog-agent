"""Tests the GitHub remediation workflow without calling GitHub."""

import pytest

from app.connectors.github import GitHubConnector, PullRequestResult


@pytest.mark.asyncio
async def test_create_remediation_pull_request_runs_all_steps(monkeypatch) -> None:
    connector = GitHubConnector("token", "org/repo")
    calls: list[str] = []

    async def create_branch(branch: str) -> None:
        calls.append(f"branch:{branch}")

    async def commit_file(branch: str, path: str, content: str, message: str) -> None:
        calls.append(f"commit:{path}")

    async def create_pr(title: str, body: str, branch: str) -> PullRequestResult:
        calls.append(f"pr:{branch}")
        return PullRequestResult("https://github.test/org/repo/pull/1", 1)

    async def comment(number: int, body: str) -> None:
        calls.append(f"comment:{number}")

    monkeypatch.setattr(connector, "create_branch", create_branch)
    monkeypatch.setattr(connector, "commit_file", commit_file)
    monkeypatch.setattr(connector, "create_pull_request", create_pr)
    monkeypatch.setattr(connector, "comment_on_pull_request", comment)

    result = await connector.create_remediation_pull_request("incident-1", "title", "body")

    assert result.url.endswith("/1")
    assert [call.split(":")[0] for call in calls] == ["branch", "commit", "pr", "comment"]
