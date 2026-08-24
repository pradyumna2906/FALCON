"""Strict schemas for the Checkpoint 8.3 analytics responses."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from falcon_api.analytics.types import (
    AccountAggregate,
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
    CategoryAggregate,
    MerchantAggregate,
)
from falcon_api.models.enums import AccountType, CategoryKind
from falcon_api.schemas.analytics import (
    CashFlowAnalyticsQuery,
    CashFlowAnalyticsResponse,
    CashFlowMetrics,
    SpendingAccount,
    SpendingAnalyticsQuery,
    SpendingAnalyticsResponse,
    SpendingCategory,
    SpendingMerchant,
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
