"""Versioned API router."""

from fastapi import APIRouter, Depends

from falcon_api.api.routes.analytics import analytics_router
from falcon_api.api.routes.assistant import assistant_router
from falcon_api.api.routes.auth import auth_router
from falcon_api.api.routes.classification import classification_router
from falcon_api.api.routes.forecasting import forecasting_router
from falcon_api.api.routes.goal_plans import goal_plan_router
from falcon_api.api.routes.goals import goal_planning_router, goal_router
from falcon_api.api.routes.imports import import_router
from falcon_api.api.routes.ledger import account_router, category_router
from falcon_api.api.routes.profile import profile_router
from falcon_api.api.routes.scenarios import scenario_router
from falcon_api.api.routes.setup import setup_router, verified_principal
from falcon_api.api.routes.transactions import (
    transaction_router,
    transfer_router,
)
from falcon_api.schemas.api import ApiIndexResponse
from falcon_api.schemas.errors import ErrorResponse

api_v1_router = APIRouter(prefix="/api/v1", tags=["api"])
api_v1_router.include_router(auth_router)
for financial_router in (
    profile_router,
    account_router,
    category_router,
    transaction_router,
    classification_router,
    transfer_router,
    import_router,
    analytics_router,
    forecasting_router,
    goal_router,
    goal_planning_router,
    goal_plan_router,
    scenario_router,
    assistant_router,
    setup_router,
):
    api_v1_router.include_router(
        financial_router,
        dependencies=[Depends(verified_principal)],
        responses={
            403: {
                "model": ErrorResponse,
                "description": "Email verification is required for financial access.",
            }
        },
    )


@api_v1_router.get(
    "",
    response_model=ApiIndexResponse,
    operation_id="get_api_v1_index",
    summary="Identify API version 1",
)
async def api_v1_index() -> ApiIndexResponse:
    """Expose a stable discovery response for the v1 API boundary."""
    return ApiIndexResponse()
