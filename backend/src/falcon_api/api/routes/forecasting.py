"""Authenticated owner-scoped cognitive forecasting routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, status

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.forecasting.application import (
    FinancialForecastService,
    ForecastGenerationCommand,
)
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.forecasting import (
    ForecastGenerationRequest,
    ForecastRunListResponse,
    ForecastRunResponse,
    ForecastRunSummaryResponse,
)


forecasting_router = APIRouter(prefix="/forecasts", tags=["forecasting"])


def forecasting_service_from(request: Request) -> FinancialForecastService:
    return cast(FinancialForecastService, request.app.state.forecasting_service)


ForecastingServiceDependency = Annotated[
    FinancialForecastService, Depends(forecasting_service_from)
]
ForecastRequestBody = Annotated[ForecastGenerationRequest, Body()]
ForecastHistoryLimit = Annotated[int, Query(ge=1, le=100)]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_FORECAST_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The forecast request or available history is insufficient.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The owner-scoped forecast was not found.",
}


@forecasting_router.post(
    "",
    response_model=ForecastRunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="generate_financial_forecast",
    summary="Generate and persist an evaluated financial forecast",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _FORECAST_VALIDATION_ERROR,
    },
)
async def generate_financial_forecast(
    payload: ForecastRequestBody,
    session: DatabaseSession,
    service: ForecastingServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ForecastRunResponse:
    run = await service.generate(
        session,
        user_id=principal.user_id,
        command=ForecastGenerationCommand(
            target=payload.target,
            granularity=payload.granularity,
            currency=payload.currency or principal.default_currency,
            history_start=payload.history_start,
            history_end=payload.history_end,
            horizon=payload.horizon,
            trusted_timezone=principal.timezone,
        ),
    )
    return ForecastRunResponse.model_validate(run)


@forecasting_router.get(
    "",
    response_model=ForecastRunListResponse,
    operation_id="list_financial_forecasts",
    summary="List recent owner-scoped forecast runs",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def list_financial_forecasts(
    session: DatabaseSession,
    service: ForecastingServiceDependency,
    principal: CurrentPrincipalDependency,
    limit: ForecastHistoryLimit = 20,
) -> ForecastRunListResponse:
    runs = await service.list_recent(
        session,
        user_id=principal.user_id,
        limit=limit,
    )
    return ForecastRunListResponse(
        items=tuple(ForecastRunSummaryResponse.model_validate(run) for run in runs)
    )


@forecasting_router.get(
    "/{run_id}",
    response_model=ForecastRunResponse,
    operation_id="get_financial_forecast",
    summary="Get one immutable owner-scoped forecast run",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_financial_forecast(
    run_id: UUID,
    session: DatabaseSession,
    service: ForecastingServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ForecastRunResponse:
    run = await service.get(
        session,
        user_id=principal.user_id,
        run_id=run_id,
    )
    return ForecastRunResponse.model_validate(run)
