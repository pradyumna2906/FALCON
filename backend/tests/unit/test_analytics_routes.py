"""API contracts for authenticated cash-flow and spending analytics."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.analytics.application import FinancialAnalyticsService
from falcon_api.analytics.budgeting import evaluate_budget
from falcon_api.analytics.health_score import evaluate_financial_health
from falcon_api.analytics.insights import InsightAnalysisStatus
from falcon_api.analytics.spending_signals import (
    SpendingSignalEvaluationStatus,
    SpendingSignalType,
)
from falcon_api.analytics.types import (
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
    BudgetDefinition,
    FinancialHealthProfileAggregate,
)
from falcon_api.api.routes.analytics import analytics_service_from
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.auth.principal import (
    AuthenticatedPrincipal,
    CurrentPrincipalService,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.models.enums import ProfileCompletionStatus
from falcon_api.schemas.analytics import (
    AnalyticsCompleteness,
    AnalyticsContext,
    AnalyticsDashboardResponse,
    AnalyticsDashboardSpending,
    AnalyticsExclusions,
    AnalyticsFreshness,
    AnalyticsPeriodResponse,
    BudgetAnalyticsResponse,
    CashFlowAnalyticsResponse,
    CashFlowMetrics,
    CashFlowPoint,
    FinancialHealthScoreResponse,
    InsightAnalyticsResponse,
    InsightAnalyticsSummary,
    MoneyMetric,
    RateMetric,
    RecurringAnalyticsResponse,
    RecurringAnalyticsSummary,
    SpendingAnalyticsResponse,
    SpendingSignalAnalyticsResponse,
    SpendingSignalAnalyticsSummary,
    SpendingSignalEvaluationResponse,
)
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

_TOKEN = "signed-analytics-access-token"
_NOW = datetime(2026, 8, 24, 8, tzinfo=UTC)


@pytest.fixture
def analytics_dependencies(
    client: TestClient,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AuthenticatedPrincipal]:
    """Override persistence, authentication, and analytics services."""
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="analytics-user@example.com",
        display_name="Analytics User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    analytics_service = AsyncMock(spec=FinancialAnalyticsService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[current_principal_service_from] = lambda: (
        principal_service
    )
    client.app.dependency_overrides[analytics_service_from] = lambda: (
        analytics_service
    )

    try:
        yield analytics_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _context() -> AnalyticsContext:
    return AnalyticsContext(
        currency="INR",
        period=AnalyticsPeriodResponse(
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 24),
            timezone="Asia/Kolkata",
            day_count=24,
        ),
        comparison_period=AnalyticsPeriodResponse(
            date_from=date(2026, 7, 8),
            date_to=date(2026, 7, 31),
            timezone="Asia/Kolkata",
            day_count=24,
        ),
        freshness=AnalyticsFreshness(
            calculated_at=_NOW,
            source_last_updated_at=_NOW,
            latest_transaction_date=date(2026, 8, 24),
        ),
        completeness=AnalyticsCompleteness(
            eligible_transaction_count=40,
            categorized_transaction_count=36,
            suggested_transaction_count=2,
            abstained_transaction_count=1,
            exclusions=AnalyticsExclusions(
                pending_count=3,
                transfer_entry_count=4,
                adjustment_count=1,
                other_currency_count=2,
            ),
        ),
    )


def _metrics() -> CashFlowMetrics:
    return CashFlowMetrics(
        gross_income=MoneyMetric(value=Decimal("10000")),
        total_expense=MoneyMetric(value=Decimal("6250")),
        net_cash_flow=MoneyMetric(value=Decimal("3750")),
        savings_amount=MoneyMetric(value=Decimal("3750")),
        savings_rate=RateMetric(value=Decimal("0.375")),
        internal_transfer_volume=MoneyMetric(value=Decimal("500")),
        net_adjustment=MoneyMetric(value=Decimal("-10")),
    )


def _cash_flow_response() -> CashFlowAnalyticsResponse:
    return CashFlowAnalyticsResponse(
        context=_context(),
        granularity=AnalyticsGranularity.MONTH,
        metrics=_metrics(),
        previous_period=_metrics(),
        series=(
            CashFlowPoint(
                period_start=date(2026, 8, 1),
                gross_income=MoneyMetric(value=Decimal("10000")),
                total_expense=MoneyMetric(value=Decimal("6250")),
                net_cash_flow=MoneyMetric(value=Decimal("3750")),
                transaction_count=40,
            ),
        ),
    )


def _spending_response() -> SpendingAnalyticsResponse:
    return SpendingAnalyticsResponse(
        context=_context(),
        total_expense=MoneyMetric(value=Decimal("6250")),
        previous_period_total_expense=MoneyMetric(value=Decimal("6000")),
        categories=(),
        merchants=(),
        accounts=(),
    )


def _recurring_response() -> RecurringAnalyticsResponse:
    context = _context().model_copy(update={"comparison_period": None})
    return RecurringAnalyticsResponse(
        context=context,
        minimum_occurrences=3,
        summary=RecurringAnalyticsSummary(
            candidate_pattern_count=0,
            detected_pattern_count=0,
            abstained_pattern_count=0,
            returned_pattern_count=0,
            truncated=False,
            detected_income_observed=MoneyMetric(value=Decimal("0")),
            detected_expense_observed=MoneyMetric(value=Decimal("0")),
        ),
        patterns=(),
    )


def _spending_signal_response() -> SpendingSignalAnalyticsResponse:
    context = _context().model_copy(update={"comparison_period": None})
    return SpendingSignalAnalyticsResponse(
        context=context,
        summary=SpendingSignalAnalyticsSummary(
            evaluated_transaction_count=0,
            detected_signal_count=0,
            potential_leak_signal_count=0,
            anomaly_signal_count=0,
            returned_signal_count=0,
            truncated=False,
        ),
        evaluations=tuple(
            SpendingSignalEvaluationResponse(
                signal_type=signal_type,
                status=SpendingSignalEvaluationStatus.INSUFFICIENT_DATA,
                source_observation_count=0,
                explanation="No eligible expense evidence was available.",
            )
            for signal_type in SpendingSignalType
        ),
        signals=(),
    )


def _budget_response() -> BudgetAnalyticsResponse:
    definition = BudgetDefinition(
        budget_id=uuid4(),
        name="August plan",
        period_start_date=date(2026, 8, 1),
        period_end_date=date(2026, 8, 31),
        currency="INR",
        overall_limit=Decimal("10000"),
        archived_at=None,
        category_limits=(),
    )
    analysis = evaluate_budget(
        definition,
        (),
        total_expense=Decimal("6250"),
        local_today=date(2026, 8, 24),
    )
    context = _context().model_copy(update={"comparison_period": None})
    return BudgetAnalyticsResponse.from_analysis(
        context=context,
        definition=definition,
        analysis=analysis,
    )


def _financial_health_response() -> FinancialHealthScoreResponse:
    summary = AnalyticsSummaryAggregate(
        gross_income=Decimal("10000"),
        total_expense=Decimal("6250"),
        internal_transfer_volume=Decimal("0"),
        net_adjustment=Decimal("0"),
        eligible_transaction_count=40,
        categorized_transaction_count=36,
        suggested_transaction_count=2,
        abstained_transaction_count=1,
        pending_count=0,
        transfer_entry_count=0,
        adjustment_count=0,
        other_currency_count=0,
        latest_transaction_date=date(2026, 8, 24),
        source_last_updated_at=_NOW,
    )
    analysis = evaluate_financial_health(
        summary=summary,
        cash_flow_buckets=(),
        expense_categories=(),
        profile=FinancialHealthProfileAggregate(
            profile_completion_status=ProfileCompletionStatus.COMPLETE,
            emergency_fund_target_months=Decimal("3"),
            liquid_balance=Decimal("50000"),
            liability_account_count=0,
            liability_payment_count=0,
            monthly_debt_payment=Decimal("0"),
            source_last_updated_at=_NOW,
        ),
        period_date_from=date(2026, 8, 1),
        period_date_to=date(2026, 8, 24),
        budget=None,
    )
    return FinancialHealthScoreResponse.from_analysis(
        context=_context().model_copy(update={"comparison_period": None}),
        analysis=analysis,
    )


def _insight_response() -> InsightAnalyticsResponse:
    return InsightAnalyticsResponse(
        context=_context().model_copy(update={"comparison_period": None}),
        status=InsightAnalysisStatus.NO_INSIGHTS,
        summary=InsightAnalyticsSummary(
            candidate_count=0,
            active_insight_count=0,
            high_severity_count=0,
            medium_severity_count=0,
            low_severity_count=0,
            returned_insight_count=0,
            truncated=False,
        ),
        insights=(),
        explanation="No recommendation threshold was crossed.",
    )


def _dashboard_response() -> AnalyticsDashboardResponse:
    cash_flow = _cash_flow_response()
    spending = _spending_response()
    return AnalyticsDashboardResponse(
        context=cash_flow.context.model_copy(update={"comparison_period": None}),
        granularity=cash_flow.granularity,
        metrics=cash_flow.metrics,
        series=cash_flow.series,
        spending=AnalyticsDashboardSpending(
            total_expense=spending.total_expense,
            categories=spending.categories,
            merchants=spending.merchants,
            accounts=spending.accounts,
        ),
    )


def test_dashboard_route_exports_one_owner_scoped_core_bundle(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, _, session, principal = analytics_dependencies
    service.dashboard_export.return_value = _dashboard_response()

    response = client.get(
        "/api/v1/analytics/dashboard",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={
            "date_from": "2026-08-01",
            "date_to": "2026-08-24",
            "currency": "inr",
            "granularity": "month",
            "limit": "10",
        },
    )

    assert response.status_code == 200
    assert response.json()["export_version"] == "2026.1"
    assert response.json()["metrics"]["total_expense"] == (
        response.json()["spending"]["total_expense"]
    )
    call = service.dashboard_export.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone
    assert call.kwargs["selection"].currency == "INR"
    assert call.kwargs["selection"].comparison.value == "none"
    assert call.kwargs["granularity"] is AnalyticsGranularity.MONTH
    assert call.kwargs["limit"] == 10


def test_cash_flow_route_uses_authenticated_context_and_safe_query(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, principal_service, session, principal = analytics_dependencies
    service.cash_flow.return_value = _cash_flow_response()

    response = client.get(
        "/api/v1/analytics/cash-flow",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={
            "date_from": "2026-08-01",
            "date_to": "2026-08-24",
            "currency": "inr",
            "comparison": "previous_period",
            "granularity": "month",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["context"]["currency"] == "INR"
    assert body["metrics"]["net_cash_flow"]["value"] == "3750.0000"
    assert body["metrics"]["savings_rate"]["value"] == "0.375000"
    assert body["series"][0]["period_start"] == "2026-08-01"
    assert "user_id" not in body
    assert "timezone_override" not in body
    principal_service.authenticate.assert_awaited_once_with(session, token=_TOKEN)
    call = service.cash_flow.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone
    assert call.kwargs["default_currency"] == principal.default_currency
    assert call.kwargs["selection"].currency == "INR"
    assert call.kwargs["granularity"] is AnalyticsGranularity.MONTH


def test_spending_route_passes_bounded_limit_and_authenticated_owner(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, _, session, principal = analytics_dependencies
    service.spending.return_value = _spending_response()

    response = client.get(
        "/api/v1/analytics/spending",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={"comparison": "none", "limit": "10"},
    )

    assert response.status_code == 200
    assert response.json()["total_expense"]["value"] == "6250.0000"
    call = service.spending.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["selection"].comparison.value == "none"
    assert call.kwargs["limit"] == 10


def test_recurring_route_passes_only_trusted_owner_and_bounded_controls(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, _, session, principal = analytics_dependencies
    service.recurring.return_value = _recurring_response()

    response = client.get(
        "/api/v1/analytics/recurring",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={
            "date_from": "2026-05-01",
            "date_to": "2026-08-24",
            "currency": "inr",
            "minimum_occurrences": "4",
            "limit": "10",
            "include_abstained": "false",
        },
    )

    assert response.status_code == 200
    assert response.json()["policy_version"] == "2026.1"
    call = service.recurring.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone
    assert call.kwargs["selection"].currency == "INR"
    assert call.kwargs["selection"].comparison.value == "none"
    assert call.kwargs["minimum_occurrences"] == 4
    assert call.kwargs["limit"] == 10
    assert call.kwargs["include_abstained"] is False


def test_spending_signal_route_passes_only_trusted_owner_and_limit(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, _, session, principal = analytics_dependencies
    service.spending_signals.return_value = _spending_signal_response()

    response = client.get(
        "/api/v1/analytics/spending-signals",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={
            "date_from": "2026-08-01",
            "date_to": "2026-08-24",
            "currency": "inr",
            "limit": "10",
        },
    )

    assert response.status_code == 200
    assert response.json()["policy_version"] == "2026.1"
    call = service.spending_signals.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone
    assert call.kwargs["selection"].currency == "INR"
    assert call.kwargs["selection"].comparison.value == "none"
    assert call.kwargs["limit"] == 10


def test_budget_route_passes_authenticated_owner_and_path_identifier(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, _, session, principal = analytics_dependencies
    response_model = _budget_response()
    service.budget.return_value = response_model

    response = client.get(
        f"/api/v1/analytics/budgets/{response_model.budget.budget_id}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["policy_version"] == "2026.1"
    assert response.json()["overall"]["spent_amount"]["value"] == "6250.0000"
    call = service.budget.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone
    assert call.kwargs["budget_id"] == response_model.budget.budget_id


def test_financial_health_route_passes_trusted_context_and_optional_budget(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, _, session, principal = analytics_dependencies
    response_model = _financial_health_response()
    service.financial_health_score.return_value = response_model
    budget_id = uuid4()

    response = client.get(
        "/api/v1/analytics/health-score",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={
            "date_from": "2026-08-01",
            "date_to": "2026-08-24",
            "currency": "inr",
            "budget_id": str(budget_id),
        },
    )

    assert response.status_code == 200
    assert response.json()["policy_version"] == "2026.1"
    assert len(response.json()["factors"]) == 7
    call = service.financial_health_score.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone
    assert call.kwargs["selection"].currency == "INR"
    assert call.kwargs["selection"].comparison.value == "none"
    assert call.kwargs["budget_id"] == budget_id


def test_insight_route_passes_trusted_context_budget_and_bounded_limit(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, _, session, principal = analytics_dependencies
    service.prioritized_insights.return_value = _insight_response()
    budget_id = uuid4()

    response = client.get(
        "/api/v1/analytics/insights",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={
            "date_from": "2026-08-01",
            "date_to": "2026-08-24",
            "currency": "inr",
            "budget_id": str(budget_id),
            "limit": "5",
        },
    )

    assert response.status_code == 200
    assert response.json()["policy_version"] == "2026.1"
    assert response.json()["status"] == "no_insights"
    call = service.prioritized_insights.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone
    assert call.kwargs["selection"].currency == "INR"
    assert call.kwargs["selection"].comparison.value == "none"
    assert call.kwargs["budget_id"] == budget_id
    assert call.kwargs["limit"] == 5


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/analytics/cash-flow", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/cash-flow", {"timezone": "UTC"}),
        ("/api/v1/analytics/cash-flow", {"date_from": "2026-08-01"}),
        ("/api/v1/analytics/cash-flow", {"granularity": "week"}),
        ("/api/v1/analytics/dashboard", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/dashboard", {"limit": "101"}),
        ("/api/v1/analytics/spending", {"limit": "101"}),
        ("/api/v1/analytics/spending", {"currency": "RUPEE"}),
        ("/api/v1/analytics/recurring", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/recurring", {"minimum_occurrences": "2"}),
        ("/api/v1/analytics/recurring", {"limit": "101"}),
        ("/api/v1/analytics/spending-signals", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/spending-signals", {"threshold": "0.5"}),
        ("/api/v1/analytics/spending-signals", {"limit": "101"}),
        ("/api/v1/analytics/budgets/not-a-uuid", {}),
        ("/api/v1/analytics/health-score", {"weight": "25"}),
        ("/api/v1/analytics/health-score", {"budget_id": "not-a-uuid"}),
        ("/api/v1/analytics/insights", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/insights", {"priority_weight": "50"}),
        ("/api/v1/analytics/insights", {"limit": "51"}),
    ],
)
def test_analytics_routes_reject_untrusted_or_invalid_query_fields(
    client: TestClient,
    analytics_dependencies,
    path: str,
    params: dict[str, str],
) -> None:
    service, _, _, _ = analytics_dependencies

    response = client.get(
        path,
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params=params,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.cash_flow.assert_not_awaited()
    service.spending.assert_not_awaited()
    service.recurring.assert_not_awaited()
    service.spending_signals.assert_not_awaited()
    service.budget.assert_not_awaited()
    service.financial_health_score.assert_not_awaited()
    service.prioritized_insights.assert_not_awaited()
    service.dashboard_export.assert_not_awaited()


def test_analytics_routes_require_authentication(
    client: TestClient,
    analytics_dependencies,
) -> None:
    service, principal_service, session, _ = analytics_dependencies
    principal_service.authenticate.side_effect = ApplicationError(
        code="invalid_access_token",
        message="The access token is invalid or expired.",
        status_code=401,
    )

    response = client.get("/api/v1/analytics/cash-flow")

    assert response.status_code == 401
    principal_service.authenticate.assert_awaited_once_with(session, token="")
    service.cash_flow.assert_not_awaited()


def test_openapi_documents_all_analytics_operations(client: TestClient) -> None:
    document = client.get("/openapi.json").json()

    assert "get" in document["paths"]["/api/v1/analytics/cash-flow"]
    assert "get" in document["paths"]["/api/v1/analytics/dashboard"]
    assert "get" in document["paths"]["/api/v1/analytics/spending"]
    assert "get" in document["paths"]["/api/v1/analytics/recurring"]
    assert "get" in document["paths"]["/api/v1/analytics/spending-signals"]
    assert "get" in document["paths"]["/api/v1/analytics/budgets/{budget_id}"]
    assert "get" in document["paths"]["/api/v1/analytics/health-score"]
    assert "get" in document["paths"]["/api/v1/analytics/insights"]
    assert (
        document["paths"]["/api/v1/analytics/dashboard"]["get"]["operationId"]
        == "get_analytics_dashboard_export"
    )
    assert set(
        document["paths"]["/api/v1/analytics/dashboard"]["get"]["responses"]
    ) >= {"200", "401", "422"}
    assert (
        document["paths"]["/api/v1/analytics/cash-flow"]["get"]["operationId"]
        == "get_cash_flow_analytics"
    )
    assert (
        document["paths"]["/api/v1/analytics/spending"]["get"]["operationId"]
        == "get_spending_analytics"
    )
    assert (
        document["paths"]["/api/v1/analytics/recurring"]["get"]["operationId"]
        == "get_recurring_analytics"
    )
    assert (
        document["paths"]["/api/v1/analytics/spending-signals"]["get"]["operationId"]
        == "get_spending_signal_analytics"
    )
    assert (
        document["paths"]["/api/v1/analytics/budgets/{budget_id}"]["get"]["operationId"]
        == "get_budget_analytics"
    )
    assert set(
        document["paths"]["/api/v1/analytics/budgets/{budget_id}"]["get"]["responses"]
    ) >= {"200", "401", "404", "422"}
    assert (
        document["paths"]["/api/v1/analytics/health-score"]["get"]["operationId"]
        == "get_financial_health_score"
    )
    assert (
        document["paths"]["/api/v1/analytics/insights"]["get"]["operationId"]
        == "get_prioritized_financial_insights"
    )
    assert set(
        document["paths"]["/api/v1/analytics/insights"]["get"]["responses"]
    ) >= {"200", "401", "404", "422"}
