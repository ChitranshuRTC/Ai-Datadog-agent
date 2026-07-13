"""Standard API error response contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """A machine-readable description of a request failure."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    """Structured error response returned by all API error handlers."""

    model_config = ConfigDict(frozen=True)

    error: ErrorDetail
    request_id: str = Field(min_length=1)
