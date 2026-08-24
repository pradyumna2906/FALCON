"""Contract checks for the approved Phase 8.1 boundary."""

from pathlib import Path

from falcon_api.schemas.analytics import (
    AnalyticsContext,
    AnalyticsRangeQuery,
    BudgetAnalyticsResponse,
    FinancialHealthAnalyticsQuery,
    FinancialHealthScoreResponse,
    RecurringAnalyticsQuery,
    SpendingSignalAnalyticsQuery,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMPLEMENTATION_DOCUMENT = (
    _REPOSITORY_ROOT / "docs" / "analytics" / "PHASE_8_IMPLEMENTATION.md"
)


def test_public_query_excludes_server_owned_context() -> None:
    properties = set(AnalyticsRangeQuery.model_json_schema()["properties"])

    assert properties == {"date_from", "date_to", "currency", "comparison"}
    for private_field in {"user_id", "timezone", "as_of", "model_confidence"}:
        assert private_field not in properties


def test_common_response_excludes_ownership_and_raw_financial_data() -> None:
    properties = set(AnalyticsContext.model_json_schema()["properties"])

    assert "user_id" not in properties
    assert "transaction_ids" not in properties
    assert "descriptions" not in properties
    assert "merchant_names" not in properties


def test_phase_document_freezes_the_approved_analytics_contract() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    required_statements = (
        "analytics contract version: `2026.1`",
        "authenticated principal",
        "inclusive calendar dates",
        "366 days",
        "trusted iana timezone",
        "posted",
        "pending",
        "internal transfers",
        "adjustments",
        "gross income",
        "total expense",
        "net cash flow",
        "savings amount",
        "savings rate",
        "cash-flow proxy",
        "currency conversion",
        "canonical `transactions.category_id`",
        "suggested",
        "abstained",
        "classification coverage",
        "not an ml probability",
        "previous-period",
        "zero-data",
        "freshness",
        "validation_error",
        "analytics_date_in_future",
        "checkpoint 8.1",
        "checkpoint 8.2",
        "phase 9",
        "no sql aggregation",
    )

    for statement in required_statements:
        assert statement in content


def test_recurring_contract_is_bounded_private_and_documented() -> None:
    properties = set(RecurringAnalyticsQuery.model_json_schema()["properties"])

    assert properties == {
        "date_from",
        "date_to",
        "currency",
        "minimum_occurrences",
        "limit",
        "include_abstained",
    }
    for private_field in {
        "user_id",
        "timezone",
        "transaction_ids",
        "confidence",
        "interval_tolerance",
        "amount_tolerance",
    }:
        assert private_field not in properties

    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    for statement in (
        "get /api/v1/analytics/recurring",
        "minimum_occurrences",
        "repeated_merchant",
        "5–9 days",
        "25–35 days",
        "0.65 × interval consistency + 0.35 × amount consistency",
        "explicitly `abstained`",
        "not a forecast",
        "at most two sql statements",
    ):
        assert statement in content


def test_spending_signal_contract_is_fixed_private_and_cautious() -> None:
    properties = set(
        SpendingSignalAnalyticsQuery.model_json_schema()["properties"]
    )

    assert properties == {"date_from", "date_to", "currency", "limit"}
    for private_field in {
        "user_id",
        "timezone",
        "transaction_ids",
        "descriptions",
        "threshold",
        "model_confidence",
    }:
        assert private_field not in properties

    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    for statement in (
        "get /api/v1/analytics/spending-signals",
        "bank-charge leakage",
        "repeated small expenses",
        "recurring subscriptions",
        "merchant concentration",
        "category spike",
        "median absolute deviation",
        "discretionary spike",
        "duplicate-like",
        "not a probability",
        "not confirmed fraud",
        "at most two sql statements",
    ):
        assert statement in content


def test_budget_contract_is_owner_private_bounded_and_non_forecasting() -> None:
    properties = set(BudgetAnalyticsResponse.model_json_schema()["properties"])
    for private_field in {
        "user_id",
        "transaction_ids",
        "descriptions",
        "model_confidence",
        "forecast_probability",
    }:
        assert private_field not in properties

    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    for statement in (
        "get /api/v1/analytics/budgets/{budget_id}",
        "remaining allowance",
        "utilization ratio",
        "daily burn rate",
        "expected spend to date",
        "pace variance",
        "pace-projected spend",
        "projected overspend amount",
        "not a probability",
        "not a phase 9 forecast",
        "at most three sql statements",
        "budget_not_found",
        "budget_not_started",
        "budget_period_unsupported",
    ):
        assert statement in content


def test_health_score_contract_is_fixed_explainable_and_non_advisory() -> None:
    query_properties = set(
        FinancialHealthAnalyticsQuery.model_json_schema()["properties"]
    )
    assert query_properties == {
        "date_from",
        "date_to",
        "currency",
        "budget_id",
    }
    response_properties = set(
        FinancialHealthScoreResponse.model_json_schema()["properties"]
    )
    for private_field in {
        "user_id",
        "weights",
        "thresholds",
        "transaction_ids",
        "credit_score",
        "forecast_probability",
    }:
        assert private_field not in query_properties
        assert private_field not in response_properties

    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    for statement in (
        "get /api/v1/analytics/health-score",
        "savings rate (25)",
        "emergency-fund readiness (20)",
        "debt-service burden (15)",
        "budget adherence (15)",
        "cash-flow stability (10)",
        "spending concentration (5)",
        "data completeness (10)",
        "at least 10 eligible transactions",
        "reweighted",
        "not a credit score",
        "not an investment recommendation",
        "not a forecast",
        "at most five sql statements",
    ):
        assert statement in content
