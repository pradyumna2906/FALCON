"""Authenticated owner-scoped Phase 10 goal routes."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, status

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.goal_planning import (
    MAX_GOAL_LIST_LIMIT,
    GoalCreateCommand,
    GoalService,
    GoalUpdateCommand,
)
from falcon_api.models.enums import GoalStatus
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.goals import (
    GoalCreateRequest,
    GoalListResponse,
    GoalResponse,
    GoalUpdateRequest,
)


goal_router = APIRouter(prefix="/goals", tags=["goals"])


def goal_service_from(request: Request) -> GoalService:
    """Return the process-scoped goal-management service."""
    return cast(GoalService, request.app.state.goal_service)


GoalServiceDependency = Annotated[GoalService, Depends(goal_service_from)]
GoalCreateBody = Annotated[GoalCreateRequest, Body()]
GoalUpdateBody = Annotated[GoalUpdateRequest, Body()]
GoalStatusFilter = Annotated[GoalStatus | None, Query(alias="status")]
GoalListLimit = Annotated[int, Query(ge=1, le=MAX_GOAL_LIST_LIMIT)]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The owner-scoped goal was not found.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The request violates the goal-planning contract.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "The goal lifecycle does not permit this operation.",
}


@goal_router.post(
    "",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_financial_goal",
    summary="Create an active financial goal",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def create_goal(
    payload: GoalCreateBody,
    session: DatabaseSession,
    service: GoalServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalResponse:
    goal = await service.create(
        session,
        user_id=principal.user_id,
        default_currency=principal.default_currency,
        trusted_timezone=principal.timezone,
        command=GoalCreateCommand(
            name=payload.name,
            goal_type=payload.goal_type,
            target_amount=payload.target_amount,
            starting_amount=payload.starting_amount,
            currency=payload.currency,
            target_date=payload.target_date,
            priority=payload.priority,
            description=payload.description,
        ),
    )
    return GoalResponse.model_validate(goal)


@goal_router.get(
    "",
    response_model=GoalListResponse,
    operation_id="list_financial_goals",
    summary="List goals owned by the authenticated user",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def list_goals(
    session: DatabaseSession,
    service: GoalServiceDependency,
    principal: CurrentPrincipalDependency,
    status_filter: GoalStatusFilter = None,
    limit: GoalListLimit = 50,
) -> GoalListResponse:
    goals = await service.list(
        session,
        user_id=principal.user_id,
        status=status_filter,
        limit=limit,
    )
    return GoalListResponse(
        items=tuple(GoalResponse.model_validate(goal) for goal in goals)
    )


@goal_router.get(
    "/{goal_id}",
    response_model=GoalResponse,
    operation_id="get_financial_goal",
    summary="Get one owner-scoped financial goal",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_goal(
    goal_id: UUID,
    session: DatabaseSession,
    service: GoalServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalResponse:
    goal = await service.get(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
    )
    return GoalResponse.model_validate(goal)


@goal_router.patch(
    "/{goal_id}",
    response_model=GoalResponse,
    operation_id="update_financial_goal",
    summary="Update one active financial goal",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def update_goal(
    goal_id: UUID,
    payload: GoalUpdateBody,
    session: DatabaseSession,
    service: GoalServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalResponse:
    goal = await service.update(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
        trusted_timezone=principal.timezone,
        command=GoalUpdateCommand(
            fields=frozenset(payload.model_fields_set),
            name=payload.name,
            goal_type=payload.goal_type,
            target_amount=payload.target_amount,
            starting_amount=payload.starting_amount,
            currency=payload.currency,
            target_date=payload.target_date,
            priority=payload.priority,
            description=payload.description,
        ),
    )
    return GoalResponse.model_validate(goal)


@goal_router.post(
    "/{goal_id}/complete",
    response_model=GoalResponse,
    operation_id="complete_financial_goal",
    summary="Mark one active financial goal as completed",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
    },
)
async def complete_goal(
    goal_id: UUID,
    session: DatabaseSession,
    service: GoalServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalResponse:
    goal = await service.complete(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
    )
    return GoalResponse.model_validate(goal)


@goal_router.post(
    "/{goal_id}/cancel",
    response_model=GoalResponse,
    operation_id="cancel_financial_goal",
    summary="Cancel one active financial goal",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
    },
)
async def cancel_goal(
    goal_id: UUID,
    session: DatabaseSession,
    service: GoalServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalResponse:
    goal = await service.cancel(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
    )
    return GoalResponse.model_validate(goal)
