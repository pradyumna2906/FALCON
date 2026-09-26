"""Versioned API router."""

from fastapi import APIRouter

from falcon_api.api.routes.assistant import assistant_router
from falcon_api.api.routes.analytics import analytics_router
from falcon_api.api.routes.auth import auth_router
from falcon_api.api.routes.classification import classification_router
from falcon_api.api.routes.forecasting import forecasting_router
from falcon_api.api.routes.goal_plans import goal_plan_router
from falcon_api.api.routes.goals import goal_planning_router, goal_router
from falcon_api.api.routes.ledger import account_router, category_router
from falcon_api.api.routes.imports import import_router
from falcon_api.api.routes.profile import profile_router
from falcon_api.api.routes.scenarios import scenario_router
from falcon_api.api.routes.transactions import (
    transaction_router,
    transfer_router,
)
from falcon_api.schemas.api import ApiIndexResponse
from falcon_api.api.routes.setup import setup_router


api_v1_router = APIRouter(prefix="/api/v1", tags=["api"])
api_v1_router.include_router(auth_router)
api_v1_router.include_router(profile_router)
api_v1_router.include_router(account_router)
api_v1_router.include_router(category_router)
api_v1_router.include_router(transaction_router)
api_v1_router.include_router(classification_router)
api_v1_router.include_router(transfer_router)
api_v1_router.include_router(import_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(forecasting_router)
api_v1_router.include_router(goal_router)
api_v1_router.include_router(goal_planning_router)
api_v1_router.include_router(goal_plan_router)
api_v1_router.include_router(scenario_router)
api_v1_router.include_router(assistant_router)
api_v1_router.include_router(setup_router)


@api_v1_router.get(
    "",
    response_model=ApiIndexResponse,
    operation_id="get_api_v1_index",
    summary="Identify API version 1",
)
async def api_v1_index() -> ApiIndexResponse:
    """Expose a stable discovery response for the v1 API boundary."""
    return ApiIndexResponse()
