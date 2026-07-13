"""Datadog webhook delivery endpoint."""

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.config.settings import get_settings
from app.connectors.datadog import DatadogConnector, DatadogWebhookValidator
from app.connectors.slack import SlackDeliveryError
from app.schemas.errors import ErrorResponse
from app.schemas.datadog import DatadogWebhookAcceptedResponse
from app.services.incident_service import IncidentService
from app.services.remediation_service import RemediationService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/datadog",
    response_model=DatadogWebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a Datadog Monitor or Watchdog incident",
    responses={
        401: {"model": ErrorResponse, "description": "Webhook authentication failed."},
        422: {"model": ErrorResponse, "description": "Webhook payload is invalid."},
        503: {"model": ErrorResponse, "description": "Slack delivery failed."},
    },
)
async def receive_datadog_webhook(request: Request) -> DatadogWebhookAcceptedResponse:
    """Validate, parse, and relay a Datadog monitor or Watchdog notification to Slack."""
    raw_body = await request.body()
    settings = get_settings()
    await DatadogWebhookValidator(settings).validate(request, raw_body)
    incident = DatadogConnector().parse_incident(raw_body)
    request.state.incident_id = incident.identifier
    service: IncidentService = request.app.state.incident_service
    try:
        thread_id = await service.notify(incident)
    except SlackDeliveryError as exc:
        logger.exception("Incident %s could not be forwarded to Slack", incident.identifier)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Incident notification delivery failed.") from exc
    if settings.auto_remediation_enabled:
        remediation_service: RemediationService = request.app.state.remediation_service
        await remediation_service.remediate(incident, thread_id)
    return DatadogWebhookAcceptedResponse(incident_id=incident.identifier, slack_thread_id=thread_id)
