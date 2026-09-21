"""Authenticated owner-scoped Phase 11 scenario-simulation routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, status

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.models.scenario import ScenarioSimulationRun
from falcon_api.scenario_simulation.application import (
    ScenarioSelectionCommand,
    ScenarioSimulationCommand,
    ScenarioSimulationService,
)
from falcon_api.scenario_simulation.persistence import MAX_SCENARIO_RUN_HISTORY
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.scenarios import (
    ScenarioComparisonListResponse,
    ScenarioComparisonResponse,
    ScenarioDefinitionSummaryResponse,
    ScenarioSelectionRequest,
    ScenarioSimulationDraftRequest,
    ScenarioSimulationListResponse,
    ScenarioSimulationRunResponse,
    ScenarioSimulationSummaryResponse,
)


scenario_router = APIRouter(
    prefix="/scenario-simulations",
    tags=["scenario-simulation"],
)


def scenario_simulation_service_from(
    request: Request,
) -> ScenarioSimulationService:
    return cast(
        ScenarioSimulationService,
        request.app.state.scenario_simulation_service,
    )


ScenarioServiceDependency = Annotated[
    ScenarioSimulationService,
    Depends(scenario_simulation_service_from),
]
ScenarioSimulationBody = Annotated[ScenarioSimulationDraftRequest, Body()]
ScenarioSelectionBody = Annotated[ScenarioSelectionRequest, Body()]
ScenarioListLimit = Annotated[
    int,
    Query(ge=1, le=MAX_SCENARIO_RUN_HISTORY),
]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The owner-scoped scenario simulation was not found.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "Trusted evidence could not produce a safe simulation.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "The scenario selection changed or is invalid for this run.",
}
_CAPACITY_ERROR = {
    "model": ErrorResponse,
    "description": "Bounded scenario-simulation capacity is unavailable.",
}


@scenario_router.post(
    "",
    response_model=ScenarioSimulationRunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="simulate_scenarios",
    summary="Generate and persist an immutable scenario simulation",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
        status.HTTP_429_TOO_MANY_REQUESTS: _CAPACITY_ERROR,
    },
)
async def simulate_scenarios(
    payload: ScenarioSimulationBody,
    session: DatabaseSession,
    service: ScenarioServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ScenarioSimulationRunResponse:
    run = await service.simulate(
        session,
        user_id=principal.user_id,
        command=ScenarioSimulationCommand(
            source_plan_id=payload.source_plan_id,
            scenarios=payload.to_domain(),
        ),
    )
    return ScenarioSimulationRunResponse.model_validate(run)


@scenario_router.get(
    "",
    response_model=ScenarioSimulationListResponse,
    operation_id="list_scenario_simulations",
    summary="List recent immutable owner-scoped scenario simulations",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def list_scenario_simulations(
    session: DatabaseSession,
    service: ScenarioServiceDependency,
    principal: CurrentPrincipalDependency,
    limit: ScenarioListLimit = 20,
) -> ScenarioSimulationListResponse:
    runs = await service.list_recent(
        session,
        user_id=principal.user_id,
        limit=limit,
    )
    return ScenarioSimulationListResponse(
        items=tuple(
            ScenarioSimulationSummaryResponse.model_validate(run)
            for run in runs
        )
    )


@scenario_router.get(
    "/{simulation_id}",
    response_model=ScenarioSimulationRunResponse,
    operation_id="get_scenario_simulation",
    summary="Get one immutable owner-scoped scenario simulation",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_scenario_simulation(
    simulation_id: UUID,
    session: DatabaseSession,
    service: ScenarioServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ScenarioSimulationRunResponse:
    run = await service.get(
        session,
        user_id=principal.user_id,
        run_id=simulation_id,
    )
    return ScenarioSimulationRunResponse.model_validate(run)


@scenario_router.get(
    "/{simulation_id}/compare",
    response_model=ScenarioComparisonListResponse,
    operation_id="compare_scenario_simulation",
    summary="Compare and rank the alternatives in one scenario simulation",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def compare_scenario_simulation(
    simulation_id: UUID,
    session: DatabaseSession,
    service: ScenarioServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ScenarioComparisonListResponse:
    run = await service.compare(
        session,
        user_id=principal.user_id,
        run_id=simulation_id,
    )
    return _comparison_response(run)


@scenario_router.post(
    "/{simulation_id}/select",
    response_model=ScenarioSimulationRunResponse,
    operation_id="select_scenario_simulation",
    summary="Compare-and-set or clear a scenario selection",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
    },
)
async def select_scenario_simulation(
    simulation_id: UUID,
    payload: ScenarioSelectionBody,
    session: DatabaseSession,
    service: ScenarioServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ScenarioSimulationRunResponse:
    run = await service.select(
        session,
        user_id=principal.user_id,
        run_id=simulation_id,
        command=ScenarioSelectionCommand(
            scenario_definition_id=payload.scenario_definition_id,
            expected_selected_scenario_id=(
                payload.expected_selected_scenario_id
            ),
        ),
    )
    return ScenarioSimulationRunResponse.model_validate(run)


@scenario_router.post(
    "/{simulation_id}/regenerate",
    response_model=ScenarioSimulationRunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="regenerate_scenario_simulation",
    summary="Replay stored assumptions into a new immutable simulation",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
        status.HTTP_429_TOO_MANY_REQUESTS: _CAPACITY_ERROR,
    },
)
async def regenerate_scenario_simulation(
    simulation_id: UUID,
    session: DatabaseSession,
    service: ScenarioServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ScenarioSimulationRunResponse:
    run = await service.regenerate(
        session,
        user_id=principal.user_id,
        run_id=simulation_id,
    )
    return ScenarioSimulationRunResponse.model_validate(run)


def _comparison_response(
    run: ScenarioSimulationRun,
) -> ScenarioComparisonListResponse:
    baseline = next(
        item for item in run.definitions if item.path_id == run.baseline_path_id
    )
    recommended = next(
        (item for item in run.comparisons if item.recommended),
        None,
    )
    return ScenarioComparisonListResponse(
        simulation_run_id=run.id,
        snapshot_id=run.snapshot_id,
        baseline_scenario_id=baseline.id,
        recommended_scenario_id=(
            recommended.scenario_definition_id
            if recommended is not None
            else None
        ),
        definitions=tuple(
            ScenarioDefinitionSummaryResponse.model_validate(item)
            for item in run.definitions
        ),
        items=tuple(
            ScenarioComparisonResponse.model_validate(item)
            for item in run.comparisons
        ),
    )
