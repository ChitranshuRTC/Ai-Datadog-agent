"""Global exception handlers with consistent JSON error responses."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging.context import request_id

logger = logging.getLogger(__name__)


def _response(request: Request, status_code: int, code: str, message: str, details: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}, "request_id": request_id.get() or request.headers.get("X-Request-ID", "unknown")},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install exception handlers for HTTP, validation, and unexpected errors."""
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _response(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", "Request validation failed.", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        code = "not_found" if exc.status_code == status.HTTP_404_NOT_FOUND else "http_error"
        return _response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API exception")
        return _response(request, status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "An unexpected error occurred.")
