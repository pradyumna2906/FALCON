"""API contracts for authenticated cash-flow and spending analytics."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.application import FinancialAnalyticsService
from falcon_api.analytics.budgeting import evaluate_budget
from falcon_api.analytics.types import AnalyticsGranularity
from falcon_api.analytics.types import BudgetDefinition
from falcon_api.analytics.spending_signals import (
    SpendingSignalEvaluationStatus,
    SpendingSignalType,
)
from falcon_api.api.routes.analytics import analytics_service_from
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.auth.principal import (
    AuthenticatedPrincipal,
    CurrentPrincipalService,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.schemas.analytics import (
    AnalyticsCompleteness,
    AnalyticsContext,
    AnalyticsExclusions,
    AnalyticsFreshness,
    AnalyticsPeriodResponse,
    CashFlowAnalyticsResponse,
    CashFlowMetrics,
    CashFlowPoint,
    BudgetAnalyticsResponse,
    MoneyMetric,
    RateMetric,
    RecurringAnalyticsResponse,
    RecurringAnalyticsSummary,
    SpendingAnalyticsResponse,
    SpendingSignalAnalyticsResponse,
    SpendingSignalAnalyticsSummary,
    SpendingSignalEvaluationResponse,
)


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


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/analytics/cash-flow", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/cash-flow", {"timezone": "UTC"}),
        ("/api/v1/analytics/cash-flow", {"date_from": "2026-08-01"}),
        ("/api/v1/analytics/cash-flow", {"granularity": "week"}),
        ("/api/v1/analytics/spending", {"limit": "101"}),
        ("/api/v1/analytics/spending", {"currency": "RUPEE"}),
        ("/api/v1/analytics/recurring", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/recurring", {"minimum_occurrences": "2"}),
        ("/api/v1/analytics/recurring", {"limit": "101"}),
        ("/api/v1/analytics/spending-signals", {"user_id": str(uuid4())}),
        ("/api/v1/analytics/spending-signals", {"threshold": "0.5"}),
        ("/api/v1/analytics/spending-signals", {"limit": "101"}),
        ("/api/v1/analytics/budgets/not-a-uuid", {}),
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
    assert "get" in document["paths"]["/api/v1/analytics/spending"]
    assert "get" in document["paths"]["/api/v1/analytics/recurring"]
    assert "get" in document["paths"]["/api/v1/analytics/spending-signals"]
    assert "get" in document["paths"]["/api/v1/analytics/budgets/{budget_id}"]
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
        document["paths"]["/api/v1/analytics/spending-signals"]["get"]
        ["operationId"]
        == "get_spending_signal_analytics"
    )
    assert (
        document["paths"]["/api/v1/analytics/budgets/{budget_id}"]["get"]
        ["operationId"]
        == "get_budget_analytics"
    )
    assert set(
        document["paths"]["/api/v1/analytics/budgets/{budget_id}"]["get"]
        ["responses"]
    ) >= {"200", "401", "404", "422"}
