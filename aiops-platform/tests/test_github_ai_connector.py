"""Tests for Claude-proposed YAML remediation pull requests, without calling GitHub."""

import pytest

from app.connectors.github_ai import GitHubAIConnector, GitHubAuthenticationError


def _connector() -> GitHubAIConnector:
    return GitHubAIConnector("token", "org/repo")


_VALID_DEPLOYMENT_YAML = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-api
spec:
  template:
    spec:
      containers:
        - name: payment-api
          resources:
            limits:
              memory: "512Mi"
"""


@pytest.mark.asyncio
async def test_create_remediation_pull_request_succeeds(monkeypatch) -> None:
    connector = _connector()
    calls: list[str] = []

    async def create_branch(branch: str) -> None:
        calls.append(f"branch:{branch}")

    async def commit_file(branch: str, path: str, content: str, message: str) -> str:
        calls.append(f"commit:{path}")
        return "abc123sha"

    async def open_pull_request(title: str, body: str, branch: str) -> str:
        calls.append(f"pr:{branch}")
        return "https://github.test/org/repo/pull/7"

    monkeypatch.setattr(connector, "_create_branch", create_branch)
    monkeypatch.setattr(connector, "_commit_file", commit_file)
    monkeypatch.setattr(connector, "_open_pull_request", open_pull_request)

    result = await connector.create_remediation_pull_request("incident-1", "payment-api", "fix memory limit", _VALID_DEPLOYMENT_YAML)

    assert result.success is True
    assert result.url == "https://github.test/org/repo/pull/7"
    assert result.commit_sha == "abc123sha"
    assert result.file_path == "k8s/payment-api/deployment.yaml"
    assert [call.split(":")[0] for call in calls] == ["branch", "commit", "pr"]


@pytest.mark.asyncio
async def test_malformed_yaml_is_rejected_without_pushing(monkeypatch) -> None:
    connector = _connector()

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("GitHub should never be reached for an invalid YAML patch.")

    monkeypatch.setattr(connector, "_create_branch", fail_if_called)
    monkeypatch.setattr(connector, "_commit_file", fail_if_called)
    monkeypatch.setattr(connector, "_open_pull_request", fail_if_called)

    result = await connector.create_remediation_pull_request("incident-1", "payment-api", "fix memory limit", "not: [valid: yaml")

    assert result.success is False
    assert result.url is None
    assert "YAML validation failed" in result.message


@pytest.mark.asyncio
async def test_non_mapping_yaml_is_rejected_without_pushing(monkeypatch) -> None:
    connector = _connector()

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("GitHub should never be reached for a non-mapping YAML patch.")

    monkeypatch.setattr(connector, "_create_branch", fail_if_called)
    monkeypatch.setattr(connector, "_commit_file", fail_if_called)
    monkeypatch.setattr(connector, "_open_pull_request", fail_if_called)

    result = await connector.create_remediation_pull_request("incident-1", "payment-api", "fix memory limit", "- one\n- two\n")

    assert result.success is False
    assert "YAML validation failed" in result.message


@pytest.mark.asyncio
async def test_empty_yaml_patch_is_rejected_without_pushing() -> None:
    connector = _connector()

    result = await connector.create_remediation_pull_request("incident-1", "payment-api", "fix memory limit", "   ")

    assert result.success is False
    assert "YAML validation failed" in result.message


@pytest.mark.asyncio
async def test_authentication_failure_returns_structured_error(monkeypatch) -> None:
    connector = _connector()

    async def create_branch(branch: str) -> None:
        raise GitHubAuthenticationError("Bad credentials")

    monkeypatch.setattr(connector, "_create_branch", create_branch)

    result = await connector.create_remediation_pull_request("incident-1", "payment-api", "fix memory limit", _VALID_DEPLOYMENT_YAML)

    assert result.success is False
    assert result.url is None
    assert "GitHub authentication failed" in result.message


@pytest.mark.asyncio
async def test_unexpected_github_error_returns_structured_error(monkeypatch) -> None:
    connector = _connector()

    async def create_branch(branch: str) -> None:
        pass

    async def commit_file(branch: str, path: str, content: str, message: str) -> str:
        raise RuntimeError("network error")

    monkeypatch.setattr(connector, "_create_branch", create_branch)
    monkeypatch.setattr(connector, "_commit_file", commit_file)

    result = await connector.create_remediation_pull_request("incident-1", "payment-api", "fix memory limit", _VALID_DEPLOYMENT_YAML)

    assert result.success is False
    assert "GitHub pull request creation failed" in result.message


@pytest.mark.parametrize(
    ("yaml_patch", "expected_filename"),
    [
        ("kind: Deployment\nmetadata:\n  name: x\n", "deployment.yaml"),
        ("kind: StatefulSet\nmetadata:\n  name: x\n", "statefulset.yaml"),
        ("kind: DaemonSet\nmetadata:\n  name: x\n", "daemonset.yaml"),
        ("kind: Kustomization\nresources: []\n", "kustomization.yaml"),
        ("replicaCount: 3\nimage:\n  tag: latest\n", "values.yaml"),
    ],
)
def test_resolve_file_path_maps_kind_to_supported_filename(yaml_patch: str, expected_filename: str) -> None:
    document = GitHubAIConnector._validate_yaml(yaml_patch)
    file_path = GitHubAIConnector._resolve_file_path("payment-api", document)

    assert file_path == f"k8s/payment-api/{expected_filename}"
