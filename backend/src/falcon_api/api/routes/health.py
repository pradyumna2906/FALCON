"""Process health endpoints."""

from fastapi import APIRouter

from falcon_api.schemas.health import HealthResponse

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
