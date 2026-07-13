"""System status endpoints."""

from fastapi import APIRouter

from app.config.settings import get_settings
from app.schemas.errors import ErrorResponse
from app.schemas.system import HealthResponse, VersionResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    responses={500: {"model": ErrorResponse, "description": "Unexpected server error."}},
)
async def health() -> HealthResponse:
    """Return the liveness status for orchestration systems."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/version", response_model=VersionResponse, summary="Service version")
async def version() -> VersionResponse:
    """Return the running service version."""
    settings = get_settings()
    return VersionResponse(service=settings.app_name, version=settings.app_version)
