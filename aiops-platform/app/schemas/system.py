"""System endpoint response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SystemResponse(BaseModel):
    """Common immutable system metadata."""

    model_config = ConfigDict(frozen=True)

    service: str
    version: str


class HealthResponse(SystemResponse):
    """Liveness endpoint payload."""

    status: Literal["healthy"]


class VersionResponse(SystemResponse):
    """Version endpoint payload."""
