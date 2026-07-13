"""Pydantic contracts for Kubernetes investigation requests and results."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvestigationRequest(BaseModel):
    """Validated namespace and pod target for a Kubernetes investigation."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    namespace: str = Field(min_length=1, max_length=253)
    pod: str = Field(min_length=1, max_length=253)

    @field_validator("namespace", "pod")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        """Prevent empty resource identifiers from reaching kubectl."""
        if not value:
            raise ValueError("must not be blank")
        return value


class PodSummary(BaseModel):
    """Relevant pod status extracted from a pod manifest."""

    model_config = ConfigDict(frozen=True)

    name: str
    phase: str
    node_name: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class EventSummary(BaseModel):
    """A concise Kubernetes event associated with the investigated pod."""

    model_config = ConfigDict(frozen=True)

    reason: str
    message: str
    event_type: str
    count: int = 0


class DeploymentSummary(BaseModel):
    """Deployment rollout and replica status relevant to an investigation."""

    model_config = ConfigDict(frozen=True)

    name: str
    desired_replicas: int = 0
    available_replicas: int = 0
    updated_replicas: int = 0


class InvestigationResult(BaseModel):
    """Collected Kubernetes evidence ready for a later AI analysis stage."""

    model_config = ConfigDict(frozen=True)

    namespace: str
    pod: PodSummary
    deployment: DeploymentSummary | None = None
    status: str
    restart_count: int
    container_status: dict[str, str]
    logs: str
    events: list[EventSummary]
    describe: str
    recommendation: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
