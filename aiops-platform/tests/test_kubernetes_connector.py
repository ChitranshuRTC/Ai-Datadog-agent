"""Unit tests for the safe asynchronous kubectl connector."""

import asyncio

import pytest

from app.connectors.exceptions import KubectlCommandError, KubernetesError, ResourceNotFound
from app.connectors.kubernetes import KubernetesConnector


class FakeProcess:
    """Minimal asyncio subprocess test double."""

    def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_get_pod_returns_parsed_json(monkeypatch) -> None:
    captured: list[tuple[object, ...]] = []

    async def create_process(*command: object, **kwargs: object) -> FakeProcess:
        captured.append(command)
        return FakeProcess(0, b'{"metadata":{"name":"api"}}', b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    connector = KubernetesConnector("kubectl-custom", 1)

    assert await connector.get_pod("default", "api") == {"metadata": {"name": "api"}}
    assert captured == [("kubectl-custom", "get", "pod", "api", "-n", "default", "-o", "json")]


@pytest.mark.asyncio
async def test_kubectl_failure_raises_typed_exception(monkeypatch) -> None:
    async def create_process(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(1, b"", b"forbidden")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    with pytest.raises(KubectlCommandError):
        await KubernetesConnector("kubectl", 1).get_pod("default", "api")


@pytest.mark.asyncio
async def test_missing_resource_raises_not_found(monkeypatch) -> None:
    async def create_process(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(1, b"", b"Error from server (NotFound): pods \"api\" not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    with pytest.raises(ResourceNotFound):
        await KubernetesConnector("kubectl", 1).get_pod("default", "api")


@pytest.mark.asyncio
@pytest.mark.parametrize(("namespace", "pod"), [("", "api"), ("default", "")])
async def test_blank_resource_identifier_is_rejected(namespace: str, pod: str) -> None:
    with pytest.raises(KubernetesError):
        await KubernetesConnector("kubectl", 1).get_pod(namespace, pod)
