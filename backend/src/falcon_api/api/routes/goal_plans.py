"""Authenticated owner-scoped persistent goal-plan routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, status

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.goal_planning.application import (
    GoalPlanGenerationCommand,
    MultiGoalOptimizationService,
)
from falcon_api.goal_planning.persistence import MAX_GOAL_PLAN_HISTORY
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.goal_plans import (
    GoalPlanGenerationRequest,
    GoalPlanListResponse,
    GoalPlanRunResponse,
    GoalPlanSummaryResponse,
)


goal_plan_router = APIRouter(prefix="/goal-plans", tags=["goal-planning"])


def goal_plan_service_from(request: Request) -> MultiGoalOptimizationService:
    return cast(
        MultiGoalOptimizationService,
        request.app.state.goal_plan_service,
    )


GoalPlanServiceDependency = Annotated[
    MultiGoalOptimizationService,
    Depends(goal_plan_service_from),
]
GoalPlanGenerationBody = Annotated[GoalPlanGenerationRequest, Body()]
GoalPlanListLimit = Annotated[int, Query(ge=1, le=MAX_GOAL_PLAN_HISTORY)]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The owner-scoped goal plan was not found.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "Trusted evidence could not produce a safe goal plan.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "The goal-plan lifecycle does not permit this operation.",
}


@goal_plan_router.post(
    "",
    response_model=GoalPlanRunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="generate_goal_plan",
    summary="Generate and persist an immutable multi-goal plan",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def generate_goal_plan(
    payload: GoalPlanGenerationBody,
    session: DatabaseSession,
    service: GoalPlanServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalPlanRunResponse:
    run = await service.generate(
        session,
        user_id=principal.user_id,
        command=GoalPlanGenerationCommand(
            currency=payload.currency or principal.default_currency,
            trusted_timezone=principal.timezone,
        ),
    )
    return GoalPlanRunResponse.model_validate(run)


@goal_plan_router.get(
    "",
    response_model=GoalPlanListResponse,
    operation_id="list_goal_plans",
    summary="List recent immutable owner-scoped goal plans",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def list_goal_plans(
    session: DatabaseSession,
    service: GoalPlanServiceDependency,
    principal: CurrentPrincipalDependency,
    limit: GoalPlanListLimit = 20,
) -> GoalPlanListResponse:
    runs = await service.list_recent(
        session,
        user_id=principal.user_id,
        limit=limit,
    )
    return GoalPlanListResponse(
        items=tuple(GoalPlanSummaryResponse.model_validate(run) for run in runs)
    )


@goal_plan_router.get(
    "/{plan_id}",
    response_model=GoalPlanRunResponse,
    operation_id="get_goal_plan",
    summary="Get one immutable owner-scoped goal plan",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_goal_plan(
    plan_id: UUID,
    session: DatabaseSession,
    service: GoalPlanServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalPlanRunResponse:
    run = await service.get(
        session,
        user_id=principal.user_id,
        plan_id=plan_id,
    )
    return GoalPlanRunResponse.model_validate(run)


@goal_plan_router.post(
    "/{plan_id}/approve",
    response_model=GoalPlanRunResponse,
    operation_id="approve_goal_plan",
    summary="Approve a generated plan without moving money",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
    },
)
async def approve_goal_plan(
    plan_id: UUID,
    session: DatabaseSession,
    service: GoalPlanServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalPlanRunResponse:
    run = await service.approve(
        session,
        user_id=principal.user_id,
        plan_id=plan_id,
    )
    return GoalPlanRunResponse.model_validate(run)


@goal_plan_router.post(
    "/{plan_id}/reject",
    response_model=GoalPlanRunResponse,
    operation_id="reject_goal_plan",
    summary="Reject a generated goal plan",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
    },
)
async def reject_goal_plan(
    plan_id: UUID,
    session: DatabaseSession,
    service: GoalPlanServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalPlanRunResponse:
    run = await service.reject(
        session,
        user_id=principal.user_id,
        plan_id=plan_id,
    )
    return GoalPlanRunResponse.model_validate(run)


@goal_plan_router.post(
    "/{plan_id}/regenerate",
    response_model=GoalPlanRunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="regenerate_goal_plan",
    summary="Create a new plan version and supersede the prior plan",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def regenerate_goal_plan(
    plan_id: UUID,
    session: DatabaseSession,
    service: GoalPlanServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalPlanRunResponse:
    run = await service.regenerate(
        session,
        user_id=principal.user_id,
        plan_id=plan_id,
        trusted_timezone=principal.timezone,
    )
    return GoalPlanRunResponse.model_validate(run)
