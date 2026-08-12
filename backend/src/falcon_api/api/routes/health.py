"""Process liveness and dependency readiness endpoints."""

from fastapi import APIRouter, Request

from falcon_api.core.config import Settings
from falcon_api.infrastructure.database import (
    assert_database_ready,
    database_resources_from,
)
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.health import HealthResponse, ReadinessResponse

health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get(
    "/live",
    response_model=HealthResponse,
    operation_id="get_liveness",
    summary="Check API liveness",
)
async def liveness() -> HealthResponse:
    """Report process liveness without querying external dependencies."""
    return HealthResponse()


@health_router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        503: {
            "model": ErrorResponse,
            "description": "A required dependency is unavailable.",
        },
    },
    operation_id="get_readiness",
    summary="Check API readiness",
)
async def readiness(request: Request) -> ReadinessResponse:
    """Report readiness only after a bounded PostgreSQL probe succeeds."""
    settings: Settings = request.app.state.settings
    await assert_database_ready(
        database_resources_from(request),
        timeout_seconds=settings.db_readiness_timeout_seconds,
    )
    return ReadinessResponse()
