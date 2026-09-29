"""Authenticated financial analytics routes."""

from typing import Annotated, cast
from uuid import UUID

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
    AnalyticsDashboardQuery,
    AnalyticsDashboardResponse,
    BudgetAnalyticsResponse,
    CashFlowAnalyticsQuery,
    CashFlowAnalyticsResponse,
    FinancialHealthAnalyticsQuery,
    FinancialHealthScoreResponse,
    InsightAnalyticsQuery,
    InsightAnalyticsResponse,
    RecurringAnalyticsQuery,
    RecurringAnalyticsResponse,
    SpendingAnalyticsQuery,
    SpendingAnalyticsResponse,
    SpendingSignalAnalyticsQuery,
    SpendingSignalAnalyticsResponse,
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
SpendingSignalQueryDependency = Annotated[SpendingSignalAnalyticsQuery, Query()]
FinancialHealthQueryDependency = Annotated[FinancialHealthAnalyticsQuery, Query()]
InsightQueryDependency = Annotated[InsightAnalyticsQuery, Query()]
DashboardQueryDependency = Annotated[AnalyticsDashboardQuery, Query()]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The analytics selection violates the bounded contract.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The requested owner-scoped budget was not found.",
}


@analytics_router.get(
    "/dashboard",
    response_model=AnalyticsDashboardResponse,
    operation_id="get_analytics_dashboard_export",
    summary="Export a consolidated core analytics dashboard bundle",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_analytics_dashboard_export(
    query: DashboardQueryDependency,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> AnalyticsDashboardResponse:
    """Share one owner-scoped summary across core frontend analytics."""
    return await service.dashboard_export(
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
        granularity=query.granularity,
        limit=query.limit,
    )


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


@analytics_router.get(
    "/spending-signals",
    response_model=SpendingSignalAnalyticsResponse,
    operation_id="get_spending_signal_analytics",
    summary="Return explainable spending-leak and anomaly signals",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_spending_signal_analytics(
    query: SpendingSignalQueryDependency,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> SpendingSignalAnalyticsResponse:
    """Evaluate fixed policies using trusted owner and timezone context."""
    return await service.spending_signals(
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
        limit=query.limit,
    )


@analytics_router.get(
    "/budgets/{budget_id}",
    response_model=BudgetAnalyticsResponse,
    operation_id="get_budget_analytics",
    summary="Return budget variance and bounded overspend risk",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_budget_analytics(
    budget_id: UUID,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> BudgetAnalyticsResponse:
    """Analyze one budget using only its authenticated owner context."""
    return await service.budget(
        session,
        user_id=principal.user_id,
        trusted_timezone=principal.timezone,
        budget_id=budget_id,
    )


@analytics_router.get(
    "/health-score",
    response_model=FinancialHealthScoreResponse,
    operation_id="get_financial_health_score",
    summary="Return an explainable financial-health score",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_financial_health_score(
    query: FinancialHealthQueryDependency,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> FinancialHealthScoreResponse:
    """Score owner-scoped evidence without accepting weights or thresholds."""
    return await service.financial_health_score(
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
        budget_id=query.budget_id,
    )


@analytics_router.get(
    "/insights",
    response_model=InsightAnalyticsResponse,
    operation_id="get_prioritized_financial_insights",
    summary="Return prioritized explainable financial recommendations",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def get_prioritized_financial_insights(
    query: InsightQueryDependency,
    session: DatabaseSession,
    service: AnalyticsServiceDependency,
    principal: CurrentPrincipalDependency,
) -> InsightAnalyticsResponse:
    """Prioritize live evidence without accepting policy weights or an owner."""
    return await service.prioritized_insights(
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
        budget_id=query.budget_id,
        limit=query.limit,
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
