"""Contract checks for the approved Phase 8.1 boundary."""

from pathlib import Path

from falcon_api.schemas.analytics import (
    AnalyticsContext,
    AnalyticsRangeQuery,
    RecurringAnalyticsQuery,
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
