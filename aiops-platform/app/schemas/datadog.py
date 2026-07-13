"""Datadog webhook API schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DatadogWebhookAcceptedResponse(BaseModel):
    """Acknowledgement returned after an incident has been dispatched."""

    model_config = ConfigDict(frozen=True)

    status: Literal["accepted"] = "accepted"
    incident_id: str = Field(min_length=1)
    slack_thread_id: str = Field(min_length=1)
