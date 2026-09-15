"""Authenticated owner-scoped Phase 10 goal routes."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.goal_planning import (
    MAX_GOAL_LIST_LIMIT,
    GoalCreateCommand,
    GoalService,
    GoalUpdateCommand,
)
from falcon_api.goal_planning.contributions import (
    ContributionCreateCommand,
    ContributionService,
)
from falcon_api.goal_planning.snapshot import GoalPlanningSnapshotService
from falcon_api.models.enums import GoalStatus
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.goals import (
    ContributionCreateRequest,
    ContributionListResponse,
    ContributionResponse,
    GoalCreateRequest,
    GoalListResponse,
    GoalPlanningSnapshotResponse,
    GoalProgressResponse,
    GoalResponse,
    GoalUpdateRequest,
)


goal_router = APIRouter(prefix="/goals", tags=["goals"])
goal_planning_router = APIRouter(
    prefix="/goal-planning",
    tags=["goal-planning"],
)


def goal_service_from(request: Request) -> GoalService:
    """Return the process-scoped goal-management service."""
    return cast(GoalService, request.app.state.goal_service)


def contribution_service_from(request: Request) -> ContributionService:
    """Return the process-scoped contribution service."""
    return cast(ContributionService, request.app.state.contribution_service)


def planning_snapshot_service_from(request: Request) -> GoalPlanningSnapshotService:
    """Return the process-scoped planning snapshot service."""
    return cast(
        GoalPlanningSnapshotService,
        request.app.state.goal_planning_snapshot_service,
    )


GoalServiceDependency = Annotated[GoalService, Depends(goal_service_from)]
ContributionServiceDependency = Annotated[
    ContributionService,
    Depends(contribution_service_from),
]
PlanningSnapshotServiceDependency = Annotated[
    GoalPlanningSnapshotService,
    Depends(planning_snapshot_service_from),
]
GoalCreateBody = Annotated[GoalCreateRequest, Body()]
GoalUpdateBody = Annotated[GoalUpdateRequest, Body()]
ContributionCreateBody = Annotated[ContributionCreateRequest, Body()]
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


@goal_planning_router.get(
    "/snapshot",
    response_model=GoalPlanningSnapshotResponse,
    operation_id="build_goal_planning_snapshot",
    summary="Build a cutoff-safe multi-goal planning snapshot",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def build_planning_snapshot(
    session: DatabaseSession,
    service: PlanningSnapshotServiceDependency,
    principal: CurrentPrincipalDependency,
    currency: Annotated[
        str | None,
        Query(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
    ] = None,
) -> GoalPlanningSnapshotResponse:
    snapshot = await service.build(
        session,
        user_id=principal.user_id,
        currency=currency or principal.default_currency,
        trusted_timezone=principal.timezone,
    )
    return GoalPlanningSnapshotResponse.model_validate(snapshot)


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


@goal_router.post(
    "/{goal_id}/contributions",
    response_model=ContributionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_goal_contribution",
    summary="Record one contribution toward an active goal",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def create_contribution(
    goal_id: UUID,
    payload: ContributionCreateBody,
    session: DatabaseSession,
    service: ContributionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ContributionResponse:
    contribution = await service.create(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
        trusted_timezone=principal.timezone,
        command=ContributionCreateCommand(
            source_type=payload.source_type,
            amount=payload.amount,
            contribution_date=payload.contribution_date,
            transaction_id=payload.transaction_id,
            note=payload.note,
        ),
    )
    return ContributionResponse.model_validate(contribution)


@goal_router.get(
    "/{goal_id}/contributions",
    response_model=ContributionListResponse,
    operation_id="list_goal_contributions",
    summary="List owner-scoped contributions for one goal",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def list_contributions(
    goal_id: UUID,
    session: DatabaseSession,
    service: ContributionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ContributionListResponse:
    contributions = await service.list(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
    )
    return ContributionListResponse(
        items=tuple(
            ContributionResponse.model_validate(item) for item in contributions
        )
    )


@goal_router.delete(
    "/{goal_id}/contributions/{contribution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_goal_contribution",
    summary="Delete one contribution from an active goal",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
    },
)
async def delete_contribution(
    goal_id: UUID,
    contribution_id: UUID,
    session: DatabaseSession,
    service: ContributionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> Response:
    await service.delete(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
        contribution_id=contribution_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@goal_router.get(
    "/{goal_id}/progress",
    response_model=GoalProgressResponse,
    operation_id="get_goal_progress",
    summary="Calculate exact contribution-aware goal progress",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_goal_progress(
    goal_id: UUID,
    session: DatabaseSession,
    service: ContributionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> GoalProgressResponse:
    progress = await service.progress(
        session,
        user_id=principal.user_id,
        goal_id=goal_id,
        trusted_timezone=principal.timezone,
    )
    return GoalProgressResponse.model_validate(progress)
