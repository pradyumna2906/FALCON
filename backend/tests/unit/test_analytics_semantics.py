"""Tests for versioned financial metric meanings."""

from decimal import Decimal

import pytest

from falcon_api.analytics.semantics import (
    ANALYTICS_CONTRACT_VERSION,
    METRIC_DEFINITIONS,
    AnalyticsConfidenceLevel,
    AnalyticsMetricCode,
    classification_completeness,
    metric_definition,
)
from falcon_api.models.enums import TransactionStatus, TransactionType


def test_metric_registry_is_complete_versioned_and_immutable() -> None:
    assert ANALYTICS_CONTRACT_VERSION == "2026.1"
    assert set(METRIC_DEFINITIONS) == set(AnalyticsMetricCode)
    with pytest.raises(TypeError):
        METRIC_DEFINITIONS[AnalyticsMetricCode.GROSS_INCOME] = (  # type: ignore[index]
            object()  # type: ignore[assignment]
        )


def test_core_cash_flow_metrics_use_posted_income_and_expense_only() -> None:
    income = metric_definition(AnalyticsMetricCode.GROSS_INCOME)
    expense = metric_definition(AnalyticsMetricCode.TOTAL_EXPENSE)
    net = metric_definition(AnalyticsMetricCode.NET_CASH_FLOW)
    savings = metric_definition(AnalyticsMetricCode.SAVINGS_AMOUNT)

    assert income.transaction_types == frozenset({TransactionType.INCOME})
    assert expense.transaction_types == frozenset({TransactionType.EXPENSE})
    assert net.transaction_types == savings.transaction_types == frozenset(
        {TransactionType.INCOME, TransactionType.EXPENSE}
    )
    for definition in (income, expense, net, savings):
        assert definition.statuses == frozenset({TransactionStatus.POSTED})
        assert definition.category_required is False


def test_transfers_adjustments_and_coverage_have_separate_semantics() -> None:
    transfer = metric_definition(AnalyticsMetricCode.INTERNAL_TRANSFER_VOLUME)
    adjustment = metric_definition(AnalyticsMetricCode.NET_ADJUSTMENT)
    coverage = metric_definition(AnalyticsMetricCode.CLASSIFICATION_COVERAGE)

    assert transfer.transaction_types == frozenset({TransactionType.TRANSFER})
    assert "one posted debit leg" in transfer.formula
    assert adjustment.transaction_types == frozenset(
        {TransactionType.ADJUSTMENT}
    )
    assert coverage.category_required is True
    assert coverage.zero_data_value == "null"


@pytest.mark.parametrize(
    ("eligible", "categorized", "coverage", "confidence"),
    [
        (0, 0, None, AnalyticsConfidenceLevel.UNAVAILABLE),
        (9, 9, Decimal("1.000000"), AnalyticsConfidenceLevel.LOW),
        (10, 5, Decimal("0.500000"), AnalyticsConfidenceLevel.LOW),
        (10, 9, Decimal("0.900000"), AnalyticsConfidenceLevel.MEDIUM),
        (30, 26, Decimal("0.866667"), AnalyticsConfidenceLevel.MEDIUM),
        (30, 27, Decimal("0.900000"), AnalyticsConfidenceLevel.HIGH),
    ],
)
def test_completeness_is_count_based_and_deterministic(
    eligible: int,
    categorized: int,
    coverage: Decimal | None,
    confidence: AnalyticsConfidenceLevel,
) -> None:
    assert classification_completeness(
        eligible_count=eligible,
        categorized_count=categorized,
    ) == (coverage, confidence)


@pytest.mark.parametrize(
    ("eligible", "categorized"),
    [(-1, 0), (1, -1), (1, 2)],
)
def test_completeness_rejects_impossible_counts(
    eligible: int,
    categorized: int,
) -> None:
    with pytest.raises(ValueError):
        classification_completeness(
            eligible_count=eligible,
            categorized_count=categorized,
        )
