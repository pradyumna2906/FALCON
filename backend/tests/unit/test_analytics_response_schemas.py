"""Strict schemas for the Checkpoint 8.3 analytics responses."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from falcon_api.analytics.types import (
    AccountAggregate,
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
    BudgetCategoryLimitDefinition,
    BudgetCategorySpendingAggregate,
    BudgetDefinition,
    CategoryAggregate,
    MerchantAggregate,
    RecurringTransactionRecord,
    SpendingSignalTransactionRecord,
)
from falcon_api.analytics.periods import AnalyticsPeriod
from falcon_api.analytics.budgeting import evaluate_budget
from falcon_api.analytics.recurring import detect_recurring_patterns
from falcon_api.analytics.spending_signals import detect_spending_signals
from falcon_api.models.enums import (
    AccountType,
    CategoryKind,
    TransactionType,
)
from falcon_api.schemas.analytics import (
    CashFlowAnalyticsQuery,
    CashFlowAnalyticsResponse,
    CashFlowMetrics,
    BudgetPerformanceResponse,
    RecurringAnalyticsQuery,
    RecurringAnalyticsSummary,
    RecurringPatternResponse,
    SpendingAccount,
    SpendingAnalyticsQuery,
    SpendingAnalyticsResponse,
    SpendingCategory,
    SpendingMerchant,
    SpendingSignalAnalyticsQuery,
    SpendingSignalAnalyticsSummary,
    SpendingSignalResponse,
    ShareMetric,
)


def _summary() -> AnalyticsSummaryAggregate:
    return AnalyticsSummaryAggregate(
        gross_income=Decimal("10000"),
        total_expense=Decimal("6250"),
        internal_transfer_volume=Decimal("500"),
        net_adjustment=Decimal("-10"),
        eligible_transaction_count=40,
        categorized_transaction_count=36,
        suggested_transaction_count=2,
        abstained_transaction_count=1,
        pending_count=3,
        transfer_entry_count=4,
        adjustment_count=1,
        other_currency_count=2,
        latest_transaction_date=None,
        source_last_updated_at=None,
    )


def test_analytics_queries_add_only_bounded_endpoint_controls() -> None:
    cash_flow_properties = set(
        CashFlowAnalyticsQuery.model_json_schema()["properties"]
    )
    spending_properties = set(
        SpendingAnalyticsQuery.model_json_schema()["properties"]
    )

    assert cash_flow_properties == {
        "date_from",
        "date_to",
        "currency",
        "comparison",
        "granularity",
    }
    assert spending_properties == {
        "date_from",
        "date_to",
        "currency",
        "comparison",
        "limit",
    }
    assert CashFlowAnalyticsQuery().granularity is AnalyticsGranularity.MONTH
    assert SpendingAnalyticsQuery().limit == 25
    for private_field in {"user_id", "timezone", "as_of"}:
        assert private_field not in cash_flow_properties
        assert private_field not in spending_properties


def test_cash_flow_metrics_use_exact_public_scales() -> None:
    metrics = CashFlowMetrics.from_aggregate(_summary())
    dumped = metrics.model_dump(mode="json")

    assert dumped == {
        "gross_income": {"value": "10000.0000"},
        "total_expense": {"value": "6250.0000"},
        "net_cash_flow": {"value": "3750.0000"},
        "savings_amount": {"value": "3750.0000"},
        "savings_rate": {"value": "0.375000"},
        "internal_transfer_volume": {"value": "500.0000"},
        "net_adjustment": {"value": "-10.0000"},
    }


def test_spending_dimension_mappers_use_expense_amounts_and_counts() -> None:
    category = SpendingCategory.from_aggregate(
        CategoryAggregate(
            category_id=uuid4(),
            parent_category_id=None,
            name="Food Delivery",
            classification_code="food_delivery",
            kind=CategoryKind.EXPENSE,
            amount=Decimal("600"),
            transaction_count=3,
        ),
        share=Decimal("0.6"),
    )
    merchant = SpendingMerchant.from_aggregate(
        MerchantAggregate(
            normalized_merchant="swiggy",
            display_name="Swiggy",
            gross_income=Decimal("0"),
            total_expense=Decimal("400"),
            transaction_count=2,
            income_transaction_count=0,
            expense_transaction_count=2,
        ),
        share=Decimal("0.4"),
    )
    account = SpendingAccount.from_aggregate(
        AccountAggregate(
            account_id=uuid4(),
            name="Primary Bank",
            account_type=AccountType.BANK,
            gross_income=Decimal("0"),
            total_expense=Decimal("1000"),
            transaction_count=5,
            income_transaction_count=0,
            expense_transaction_count=5,
        ),
        share=Decimal("1"),
    )

    assert category.model_dump(mode="json")["amount"]["value"] == "600.0000"
    assert category.share.value == Decimal("0.600000")
    assert merchant.transaction_count == 2
    assert merchant.amount.value == Decimal("400.0000")
    assert account.transaction_count == 5
    assert account.share.value == Decimal("1.000000")


def test_spending_category_mapper_rejects_income_category() -> None:
    aggregate = CategoryAggregate(
        category_id=uuid4(),
        parent_category_id=None,
        name="Salary",
        classification_code="salary",
        kind=CategoryKind.INCOME,
        amount=Decimal("10000"),
        transaction_count=1,
    )

    with pytest.raises(ValueError, match="expense kind"):
        SpendingCategory.from_aggregate(
            aggregate,
            share=Decimal("1"),
        )


def test_response_models_exclude_owner_and_raw_transaction_fields() -> None:
    for model in (CashFlowAnalyticsResponse, SpendingAnalyticsResponse):
        properties = set(model.model_json_schema()["properties"])
        assert "user_id" not in properties
        assert "transaction_ids" not in properties
        assert "descriptions" not in properties

    with pytest.raises(ValidationError):
        SpendingAnalyticsQuery(limit=101)
    with pytest.raises(ValidationError, match="between zero and one"):
        ShareMetric(value=Decimal("1.000001"))


def test_recurring_query_exposes_only_bounded_detection_controls() -> None:
    properties = set(RecurringAnalyticsQuery.model_json_schema()["properties"])

    assert properties == {
        "date_from",
        "date_to",
        "currency",
        "minimum_occurrences",
        "limit",
        "include_abstained",
    }
    query = RecurringAnalyticsQuery(currency="inr")
    assert query.currency == "INR"
    assert query.minimum_occurrences == 3
    assert query.limit == 25
    assert query.include_abstained is True
    for values in (
        {"minimum_occurrences": 2},
        {"minimum_occurrences": 13},
        {"limit": 101},
        {"date_from": date(2026, 8, 1)},
    ):
        with pytest.raises(ValidationError):
            RecurringAnalyticsQuery.model_validate(values)


def test_recurring_pattern_schema_is_exact_and_transaction_private() -> None:
    records = tuple(
        RecurringTransactionRecord(
            transaction_date=observed,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("799"),
            normalized_merchant="netflix",
            display_name="Netflix",
            classification_code="streaming",
            category_name="Streaming",
        )
        for observed in (
            date(2026, 5, 1),
            date(2026, 6, 1),
            date(2026, 7, 1),
        )
    )

    response = RecurringPatternResponse.from_pattern(
        detect_recurring_patterns(records)[0]
    )
    dumped = response.model_dump(mode="json")

    assert dumped["pattern_type"] == "subscription"
    assert dumped["confidence"]["value"] == "1.000000"
    assert dumped["median_interval_days"] == "30.50"
    assert dumped["median_amount"]["value"] == "799.0000"
    assert dumped["observed_total"]["value"] == "2397.0000"
    assert "transaction_ids" not in dumped
    assert "descriptions" not in dumped

    with pytest.raises(ValidationError, match="dates must be ordered"):
        RecurringPatternResponse.model_validate(
            dumped
            | {
                "first_observed_date": "2026-08-01",
                "last_observed_date": "2026-06-01",
            }
        )


def test_recurring_summary_rejects_impossible_subsets_and_negative_totals() -> None:
    valid = {
        "candidate_pattern_count": 1,
        "detected_pattern_count": 1,
        "abstained_pattern_count": 0,
        "returned_pattern_count": 1,
        "truncated": False,
        "detected_income_observed": {"value": "100.0000"},
        "detected_expense_observed": {"value": "0.0000"},
    }

    with pytest.raises(ValidationError, match="must equal candidate"):
        RecurringAnalyticsSummary.model_validate(
            valid | {"abstained_pattern_count": 1}
        )
    with pytest.raises(ValidationError, match="cannot be negative"):
        RecurringAnalyticsSummary.model_validate(
            valid | {"detected_income_observed": {"value": "-1.0000"}}
        )
    with pytest.raises(ValidationError, match="cannot exceed candidate"):
        RecurringAnalyticsSummary.model_validate(
            valid | {"returned_pattern_count": 2}
        )


def test_spending_signal_query_is_bounded_and_server_context_is_private() -> None:
    properties = set(
        SpendingSignalAnalyticsQuery.model_json_schema()["properties"]
    )

    assert properties == {"date_from", "date_to", "currency", "limit"}
    query = SpendingSignalAnalyticsQuery(currency="inr")
    assert query.currency == "INR"
    assert query.limit == 25
    for values in (
        {"limit": 0},
        {"limit": 101},
        {"date_to": date(2026, 8, 1)},
    ):
        with pytest.raises(ValidationError):
            SpendingSignalAnalyticsQuery.model_validate(values)
    for private in {"user_id", "timezone", "threshold", "transaction_ids"}:
        assert private not in properties


def test_spending_signal_schema_uses_exact_scales_and_hides_source_rows() -> None:
    period = AnalyticsPeriod(
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        timezone="Asia/Kolkata",
    )
    records = (
        SpendingSignalTransactionRecord(
            transaction_date=date(2026, 8, 2),
            amount=Decimal("25"),
            normalized_merchant="bank",
            display_name="Bank",
            classification_code="bank_charges",
            category_name="Bank Charges",
        ),
        SpendingSignalTransactionRecord(
            transaction_date=date(2026, 8, 9),
            amount=Decimal("50"),
            normalized_merchant="bank",
            display_name="Bank",
            classification_code="bank_charges",
            category_name="Bank Charges",
        ),
    )
    signal = detect_spending_signals(
        records,
        period=period,
        total_expense=Decimal("75"),
    ).signals[0]

    dumped = SpendingSignalResponse.from_signal(signal).model_dump(mode="json")

    assert dumped["signal_type"] == "bank_charge_leakage"
    assert dumped["evidence_score"]["value"] == "0.500000"
    assert dumped["observed_amount"]["value"] == "75.0000"
    assert dumped["share_of_total_expense"]["value"] == "1.000000"
    assert "transaction_ids" not in dumped
    assert "descriptions" not in dumped


def test_spending_signal_summary_rejects_impossible_counts() -> None:
    valid = {
        "evaluated_transaction_count": 10,
        "detected_signal_count": 2,
        "potential_leak_signal_count": 1,
        "anomaly_signal_count": 1,
        "returned_signal_count": 2,
        "truncated": False,
    }

    with pytest.raises(ValidationError, match="must equal detected"):
        SpendingSignalAnalyticsSummary.model_validate(
            valid | {"anomaly_signal_count": 2}
        )
    with pytest.raises(ValidationError, match="cannot exceed detected"):
        SpendingSignalAnalyticsSummary.model_validate(
            valid | {"returned_signal_count": 3}
        )


def test_budget_performance_schema_preserves_exact_pace_metrics() -> None:
    category_id = uuid4()
    definition = BudgetDefinition(
        budget_id=uuid4(),
        name="August plan",
        period_start_date=date(2026, 8, 1),
        period_end_date=date(2026, 8, 31),
        currency="INR",
        overall_limit=Decimal("10000"),
        archived_at=None,
        category_limits=(
            BudgetCategoryLimitDefinition(
                category_id=category_id,
                name="Food Delivery",
                classification_code="food_delivery",
                limit_amount=Decimal("3000"),
            ),
        ),
    )
    analysis = evaluate_budget(
        definition,
        (
            BudgetCategorySpendingAggregate(
                category_id=category_id,
                amount=Decimal("1200"),
                transaction_count=3,
            ),
        ),
        total_expense=Decimal("2000"),
        local_today=date(2026, 8, 10),
    )

    dumped = BudgetPerformanceResponse.from_performance(
        analysis.overall
    ).model_dump(mode="json")

    assert dumped["limit_amount"]["value"] == "10000.0000"
    assert dumped["spent_amount"]["value"] == "2000.0000"
    assert dumped["remaining_allowance"]["value"] == "8000.0000"
    assert dumped["period_progress_ratio"]["value"] == "0.322581"
    assert dumped["daily_burn_rate"]["value"] == "200.0000"
    assert dumped["pace_projected_spend"]["value"] == "6200.0000"
    assert dumped["risk_level"] == "low"
    assert dumped["warning_status"] == "within_budget"


def test_budget_performance_schema_rejects_limit_relationship_mismatch() -> None:
    unavailable = {
        "limit_amount": None,
        "spent_amount": {"value": "100.0000"},
        "remaining_allowance": None,
        "utilization_ratio": {"value": None},
        "period_progress_ratio": {"value": "0.500000"},
        "elapsed_days": 15,
        "remaining_days": 16,
        "daily_burn_rate": {"value": "6.6667"},
        "expected_spend_to_date": None,
        "pace_variance": None,
        "pace_projected_spend": None,
        "projected_variance": None,
        "projected_overspend_amount": None,
        "risk_level": "unavailable",
        "warning_status": "unavailable",
    }
    assert BudgetPerformanceResponse.model_validate(unavailable).limit_amount is None

    with pytest.raises(ValidationError, match="require a stored limit"):
        BudgetPerformanceResponse.model_validate(
            unavailable
            | {"pace_projected_spend": {"value": "200.0000"}}
        )
    with pytest.raises(ValidationError, match="complete budget performance"):
        BudgetPerformanceResponse.model_validate(
            unavailable
            | {
                "limit_amount": {"value": "1000.0000"},
                "risk_level": "low",
                "warning_status": "within_budget",
            }
        )
