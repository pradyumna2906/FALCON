"""Authenticated cash-flow, spending, and recurrence analytics routes."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, status

from falcon_api.analytics.application import (
    AnalyticsSelection,
    FinancialAnalyticsService,
)
from falcon_api.analytics.semantics import AnalyticsComparisonMode
from falcon_api.api.routes.auth import (
    CurrentPrincipalDependency,
    DatabaseSession,
)
from falcon_api.schemas.analytics import (
    CashFlowAnalyticsQuery,
    CashFlowAnalyticsResponse,
    RecurringAnalyticsQuery,
    RecurringAnalyticsResponse,
    SpendingAnalyticsQuery,
    SpendingAnalyticsResponse,
)
from falcon_api.schemas.errors import ErrorResponse


analytics_router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
)


def analytics_service_from(request: Request) -> FinancialAnalyticsService:
    """Return the process-scoped financial-analytics service."""
    return cast(
        FinancialAnalyticsService,
        request.app.state.analytics_service,
    )


AnalyticsServiceDependency = Annotated[
    FinancialAnalyticsService,
    Depends(analytics_service_from),
]
CashFlowQueryDependency = Annotated[CashFlowAnalyticsQuery, Query()]
SpendingQueryDependency = Annotated[SpendingAnalyticsQuery, Query()]
RecurringQueryDependency = Annotated[RecurringAnalyticsQuery, Query()]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The analytics selection violates the bounded contract.",
}


@analytics_router.get(
    "/cash-flow",
    response_model=CashFlowAnalyticsResponse,
    operation_id="get_cash_flow_analytics",
    summary="Return cash-flow metrics and an observed trend",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_cash_flow_analytics(
    query: CashFlowQueryDependency,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> CashFlowAnalyticsResponse:
    """Return exact metrics using only trusted owner and timezone context."""
    return await service.cash_flow(
        session,
        user_id=principal.user_id,
        trusted_timezone=principal.timezone,
        default_currency=principal.default_currency,
        selection=_selection(query),
        granularity=query.granularity,
    )


@analytics_router.get(
    "/spending",
    response_model=SpendingAnalyticsResponse,
    operation_id="get_spending_analytics",
    summary="Return expense totals and bounded distributions",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_spending_analytics(
    query: SpendingQueryDependency,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> SpendingAnalyticsResponse:
    """Return owner-scoped category, merchant, and account spending."""
    return await service.spending(
        session,
        user_id=principal.user_id,
        trusted_timezone=principal.timezone,
        default_currency=principal.default_currency,
        selection=_selection(query),
        limit=query.limit,
    )


@analytics_router.get(
    "/recurring",
    response_model=RecurringAnalyticsResponse,
    operation_id="get_recurring_analytics",
    summary="Return recurring transaction evidence and abstentions",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_recurring_analytics(
    query: RecurringQueryDependency,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> RecurringAnalyticsResponse:
    """Detect recurring patterns using trusted owner and timezone context."""
    return await service.recurring(
        session,
        user_id=principal.user_id,
        trusted_timezone=principal.timezone,
        default_currency=principal.default_currency,
        selection=AnalyticsSelection(
            date_from=query.date_from,
            date_to=query.date_to,
            currency=query.currency,
            comparison=AnalyticsComparisonMode.NONE,
        ),
        minimum_occurrences=query.minimum_occurrences,
        limit=query.limit,
        include_abstained=query.include_abstained,
    )


def _selection(
    query: CashFlowAnalyticsQuery | SpendingAnalyticsQuery,
) -> AnalyticsSelection:
    return AnalyticsSelection(
        date_from=query.date_from,
        date_to=query.date_to,
        currency=query.currency,
        comparison=query.comparison,
    )
