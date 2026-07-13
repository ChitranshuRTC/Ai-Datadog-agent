"""Root API router."""

from fastapi import APIRouter

from app.api.routes.system import router as system_router
from app.api.routes.datadog import router as datadog_router

api_router = APIRouter()
api_router.include_router(system_router, tags=["system"])
api_router.include_router(datadog_router, prefix="/webhooks", tags=["webhooks"])
