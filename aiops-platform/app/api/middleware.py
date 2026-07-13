"""HTTP middleware for request correlation and structured access logging."""

import logging
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.logging.context import correlation_id, incident_id, request_id

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign IDs to each request and emit a JSON access log on completion."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process one request with correlation context and execution timing."""
        request_value = request.headers.get("X-Request-ID") or str(uuid4())
        correlation_value = request.headers.get("X-Correlation-ID") or request_value
        request_token = request_id.set(request_value)
        correlation_token = correlation_id.set(correlation_value)
        incident_token = incident_id.set(request.headers.get("X-Incident-ID"))
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_value
            response.headers["X-Correlation-ID"] = correlation_value
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            status_code = locals().get("response", Response(status_code=500)).status_code
            log_incident_id = getattr(request.state, "incident_id", incident_id.get())
            logger.info("request_completed", extra={"status_code": status_code, "execution_time_ms": duration_ms, "incident_id": log_incident_id})
            incident_id.reset(incident_token)
            correlation_id.reset(correlation_token)
            request_id.reset(request_token)
