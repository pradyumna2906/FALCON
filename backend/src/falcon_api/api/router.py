"""Versioned API router."""

from fastapi import APIRouter

from falcon_api.schemas.api import ApiIndexResponse

api_v1_router = APIRouter(prefix="/api/v1", tags=["api"])


@api_v1_router.get(
    "",
    response_model=ApiIndexResponse,
    operation_id="get_api_v1_index",
    summary="Identify API version 1",
)
async def api_v1_index() -> ApiIndexResponse:
    """Expose a stable discovery response for the v1 API boundary."""
    return ApiIndexResponse()
