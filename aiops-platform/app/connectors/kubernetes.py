"""Asynchronous kubectl adapter used for Kubernetes investigation."""

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from typing import Any, Literal

from app.connectors.exceptions import KubectlCommandError, KubernetesError, ResourceNotFound

OutputFormat = Literal["json", "text"]
NOT_FOUND_MARKERS = ("notfound", "not found", "the server could not find")


class KubernetesConnector:
    """Executes bounded, argument-safe kubectl commands without blocking the event loop."""

    def __init__(self, kubectl_path: str, timeout_seconds: float, logger: logging.Logger | None = None) -> None:
        """Create a connector with an injectable executable path, timeout, and logger."""
        self._kubectl_path = kubectl_path
        self._timeout_seconds = timeout_seconds
        self._logger = logger or logging.getLogger(__name__)

    async def get_pod(self, namespace: str, pod: str) -> dict[str, Any]:
        """Fetch one pod manifest as parsed JSON for status and ownership analysis."""
        return await self._run(("get", "pod", pod, "-n", namespace, "-o", "json"), "json", namespace, pod)

    async def describe_pod(self, namespace: str, pod: str) -> str:
        """Fetch the human-readable pod description containing scheduler diagnostics."""
        return await self._run(("describe", "pod", pod, "-n", namespace), "text", namespace, pod)

    async def get_logs(self, namespace: str, pod: str, tail_lines: int = 200) -> str:
        """Fetch recent log output from all containers in a pod."""
        if tail_lines < 1:
            raise KubernetesError("tail_lines must be greater than zero.")
        return await self._run(("logs", pod, "-n", namespace, "--all-containers", f"--tail={tail_lines}"), "text", namespace, pod)

    async def get_events(self, namespace: str, pod: str) -> dict[str, Any]:
        """Fetch Kubernetes events directly associated with a pod as JSON."""
        selector = f"involvedObject.name={pod}"
        return await self._run(("get", "events", "-n", namespace, "--field-selector", selector, "-o", "json"), "json", namespace, pod)

    async def get_deployment(self, namespace: str, deployment: str) -> dict[str, Any]:
        """Fetch a deployment manifest as JSON for rollout context."""
        return await self._run(("get", "deployment", deployment, "-n", namespace, "-o", "json"), "json", namespace, None)

    async def get_pods(self, namespace: str) -> dict[str, Any]:
        """List all pods in a namespace as parsed JSON."""
        return await self._run(("get", "pods", "-n", namespace, "-o", "json"), "json", namespace, None)

    async def get_pods_by_label(self, namespace: str, label_selector: str) -> dict[str, Any]:
        """List pods matching a Kubernetes label selector as parsed JSON."""
        if not label_selector.strip():
            raise KubernetesError("label_selector must not be blank.")
        return await self._run(("get", "pods", "-n", namespace, "-l", label_selector, "-o", "json"), "json", namespace, None)

    async def restart_deployment(self, namespace: str, deployment: str) -> str:
        """Request a rolling restart of a deployment for an approved remediation."""
        return await self._run(("rollout", "restart", f"deployment/{deployment}", "-n", namespace), "text", namespace, None)

    async def rollout_status(self, namespace: str, deployment: str, timeout_seconds: int = 120) -> str:
        """Wait for a deployment rollout and return kubectl's status output."""
        if timeout_seconds < 1:
            raise KubernetesError("timeout_seconds must be greater than zero.")
        timeout = f"--timeout={timeout_seconds}s"
        return await self._run(("rollout", "status", f"deployment/{deployment}", "-n", namespace, timeout), "text", namespace, None)

    async def _run(self, arguments: Sequence[str], output_format: OutputFormat, namespace: str, pod: str | None) -> dict[str, Any] | str:
        """Execute one kubectl command and convert its output to a safe return type."""
        self._validate_identifier(namespace, "namespace")
        if pod is not None:
            self._validate_identifier(pod, "pod")
        command = (self._kubectl_path, *arguments)
        started = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
        except FileNotFoundError as exc:
            self._log_failure(command, namespace, pod, started, "kubectl executable not found")
            raise KubernetesError(f"kubectl executable was not found: {self._kubectl_path}") from exc
        except TimeoutError as exc:
            self._log_failure(command, namespace, pod, started, "kubectl command timed out")
            raise KubernetesError(f"kubectl command exceeded {self._timeout_seconds} seconds.") from exc
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        self._log_command(command, namespace, pod, duration_ms, process.returncode)
        return self._parse_result(command, process.returncode, stdout, stderr, output_format)

    def _parse_result(self, command: tuple[str, ...], return_code: int, stdout: bytes, stderr: bytes, output_format: OutputFormat) -> dict[str, Any] | str:
        """Raise typed errors or return decoded JSON/text for a completed command."""
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if return_code != 0:
            if any(marker in stderr_text.lower() for marker in NOT_FOUND_MARKERS):
                raise ResourceNotFound(stderr_text or "Kubernetes resource was not found.")
            raise KubectlCommandError(command, return_code, stderr_text or "kubectl returned no error output.")
        output = stdout.decode("utf-8", errors="replace").strip()
        if output_format == "text":
            return output
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise KubernetesError("kubectl returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise KubernetesError("kubectl JSON output must be an object.")
        return parsed

    def _log_command(self, command: tuple[str, ...], namespace: str, pod: str | None, duration_ms: float, status_code: int) -> None:
        """Emit structured operational metadata for every kubectl invocation."""
        self._logger.info("kubectl_command_completed", extra={"command": command, "namespace": namespace, "pod": pod, "execution_time_ms": duration_ms, "status_code": status_code})

    def _log_failure(self, command: tuple[str, ...], namespace: str, pod: str | None, started: float, message: str) -> None:
        """Log execution failures that occur before a process produces a return code."""
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        self._logger.error(message, extra={"command": command, "namespace": namespace, "pod": pod, "execution_time_ms": duration_ms, "status_code": 500})

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> None:
        """Reject blank resource identifiers before creating a child process."""
        if not value or not value.strip():
            raise KubernetesError(f"{field_name} must not be blank.")
