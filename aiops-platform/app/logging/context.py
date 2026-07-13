"""Request-scoped structured logging context."""

from contextvars import ContextVar, Token

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
incident_id: ContextVar[str | None] = ContextVar("incident_id", default=None)


def set_incident_id(value: str | None) -> Token[str | None]:
    """Attach an incident identifier to log records in the current request."""
    return incident_id.set(value)
