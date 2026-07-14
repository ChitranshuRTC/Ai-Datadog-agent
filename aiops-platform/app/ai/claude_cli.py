"""Runs the local Claude CLI as a subprocess and returns its raw text response.

This module uses the Claude Code CLI exclusively. It never calls the Anthropic
SDK or REST API and never requires an API key -- authentication is whatever
the locally installed `claude` executable is already configured with. Tool
use is disabled for every invocation, so the model can only reason and
respond in text; it can never execute shell commands on this host.
"""

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class ClaudeCLIError(RuntimeError):
    """Raised when the Claude CLI cannot be invoked or returns an unusable result."""


class ClaudeCLIClient:
    """Invokes the locally installed `claude` executable in non-interactive print mode."""

    def __init__(self, executable: str = "claude", timeout_seconds: float = 120.0) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def run(self, prompt: str) -> str:
        """Send a prompt to Claude CLI over stdin and return its final text response.

        Tool use is disabled (`--allowedTools ""`) so Claude can only analyze
        and respond -- it is never able to execute shell commands, edit files,
        or reach the network while producing this response.
        """
        command = (self._executable, "-p", "--output-format", "json", "--allowedTools", "")
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ClaudeCLIError(f"Claude CLI executable was not found: {self._executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCLIError(f"Claude CLI did not respond within {self._timeout_seconds} seconds.") from exc
        if completed.returncode != 0:
            raise ClaudeCLIError(f"Claude CLI exited with status {completed.returncode}: {completed.stderr.strip()}")
        return self._extract_result(completed.stdout)

    @staticmethod
    def _extract_result(stdout: str) -> str:
        """Unwrap the CLI's JSON envelope and return the assistant's final text."""
        try:
            envelope: Any = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeCLIError("Claude CLI did not return a valid JSON envelope.") from exc
        if not isinstance(envelope, dict) or envelope.get("subtype") != "success":
            raise ClaudeCLIError(f"Claude CLI did not complete successfully: {stdout[:500]}")
        result = envelope.get("result")
        if not isinstance(result, str) or not result.strip():
            raise ClaudeCLIError("Claude CLI returned an empty response.")
        return result
