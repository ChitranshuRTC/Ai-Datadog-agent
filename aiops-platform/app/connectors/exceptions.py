"""Typed failures raised by infrastructure connectors."""


class KubernetesError(Exception):
    """Base class for Kubernetes investigation failures."""


class KubectlCommandError(KubernetesError):
    """Raised when a kubectl command exits unsuccessfully."""

    def __init__(self, command: tuple[str, ...], return_code: int, stderr: str) -> None:
        """Preserve command context without exposing it through generic exceptions."""
        super().__init__(f"kubectl command failed with exit code {return_code}: {stderr}")
        self.command = command
        self.return_code = return_code
        self.stderr = stderr


class ResourceNotFound(KubernetesError):
    """Raised when kubectl reports that the requested resource does not exist."""
