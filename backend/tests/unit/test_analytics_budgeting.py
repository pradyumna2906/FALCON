"""Deterministic budget variance and pace-risk policy coverage."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from falcon_api.analytics.budgeting import (
    BudgetAnalysisStatus,
    BudgetRiskLevel,
    BudgetWarningStatus,
    evaluate_budget,
)
from falcon_api.analytics.types import (
    BudgetCategoryLimitDefinition,
    BudgetCategorySpendingAggregate,
    BudgetDefinition,
)


_CATEGORY_ID = UUID("11111111-1111-1111-1111-111111111111")


def _definition(
    *,
    overall_limit: str | None = "10000",
    start: date = date(2026, 8, 1),
    end: date = date(2026, 8, 31),
    with_category: bool = True,
) -> BudgetDefinition:
    return BudgetDefinition(
        budget_id=uuid4(),
        name="August plan",
        period_start_date=start,
        period_end_date=end,
        currency="INR",
        overall_limit=(Decimal(overall_limit) if overall_limit is not None else None),
        archived_at=None,
        category_limits=(
            (
                BudgetCategoryLimitDefinition(
                    category_id=_CATEGORY_ID,
                    name="Food Delivery",
                    classification_code="food_delivery",
                    limit_amount=Decimal("3000"),
                ),
            )
            if with_category
            else ()
        ),
    )


def _category_spending(
    amount: str,
    *,
    category_id: UUID = _CATEGORY_ID,
    count: int = 2,
) -> tuple[BudgetCategorySpendingAggregate, ...]:
    return (
        BudgetCategorySpendingAggregate(
            category_id=category_id,
            amount=Decimal(amount),
            transaction_count=count,
        ),
    )


def test_active_budget_uses_exact_progress_burn_and_pace_variance() -> None:
    result = evaluate_budget(
        _definition(),
        _category_spending("1200"),
        total_expense=Decimal("2000"),
        local_today=date(2026, 8, 10),
    )

    overall = result.overall
    assert result.status is BudgetAnalysisStatus.ACTIVE
    assert result.observed_to == date(2026, 8, 10)
    assert overall.elapsed_days == 10
    assert overall.remaining_days == 21
    assert overall.period_progress_ratio == Decimal("0.322581")
    assert overall.spent_amount == Decimal("2000.0000")
    assert overall.remaining_allowance == Decimal("8000.0000")
    assert overall.utilization_ratio == Decimal("0.200000")
    assert overall.daily_burn_rate == Decimal("200.0000")
    assert overall.expected_spend_to_date == Decimal("3225.8100")
    assert overall.pace_variance == Decimal("1225.8100")
    assert overall.pace_projected_spend == Decimal("6200.0000")
    assert overall.projected_variance == Decimal("3800.0000")
    assert overall.projected_overspend_amount == Decimal("0.0000")
    assert overall.risk_level is BudgetRiskLevel.LOW
    assert overall.warning_status is BudgetWarningStatus.WITHIN_BUDGET
    assert result.configured_category_spend == Decimal("1200.0000")
    assert result.outside_configured_categories == Decimal("800.0000")


@pytest.mark.parametrize(
    ("spent", "risk", "warning", "projected_overspend"),
    [
        (
            "3300",
            BudgetRiskLevel.MEDIUM,
            BudgetWarningStatus.PROJECTED_OVERSPEND,
            "230.0000",
        ),
        (
            "4000",
            BudgetRiskLevel.HIGH,
            BudgetWarningStatus.PROJECTED_OVERSPEND,
            "2400.0000",
        ),
        (
            "11000",
            BudgetRiskLevel.HIGH,
            BudgetWarningStatus.OVER_LIMIT,
            "24100.0000",
        ),
    ],
)
def test_active_risk_bands_are_deterministic_pace_not_probability(
    spent: str,
    risk: BudgetRiskLevel,
    warning: BudgetWarningStatus,
    projected_overspend: str,
) -> None:
    result = evaluate_budget(
        _definition(with_category=False),
        (),
        total_expense=Decimal(spent),
        local_today=date(2026, 8, 10),
    )

    assert result.overall.risk_level is risk
    assert result.overall.warning_status is warning
    assert result.overall.projected_overspend_amount == Decimal(projected_overspend)


def test_high_utilization_can_warn_without_claiming_projected_overspend() -> None:
    result = evaluate_budget(
        _definition(with_category=False),
        (),
        total_expense=Decimal("8500"),
        local_today=date(2026, 8, 28),
    )

    assert result.overall.utilization_ratio == Decimal("0.850000")
    assert result.overall.pace_projected_spend == Decimal("9410.7143")
    assert result.overall.risk_level is BudgetRiskLevel.LOW
    assert result.overall.warning_status is BudgetWarningStatus.APPROACHING_LIMIT


def test_completed_budget_uses_realized_spend_instead_of_extrapolation() -> None:
    result = evaluate_budget(
        _definition(),
        _category_spending("2500"),
        total_expense=Decimal("9000"),
        local_today=date(2026, 9, 5),
    )

    assert result.status is BudgetAnalysisStatus.COMPLETED
    assert result.observed_to == date(2026, 8, 31)
    assert result.overall.remaining_days == 0
    assert result.overall.period_progress_ratio == Decimal("1.000000")
    assert result.overall.pace_projected_spend == Decimal("9000.0000")
    assert result.overall.projected_variance == Decimal("1000.0000")
    assert result.overall.warning_status is BudgetWarningStatus.WITHIN_BUDGET


def test_missing_overall_limit_keeps_usage_but_marks_risk_unavailable() -> None:
    result = evaluate_budget(
        _definition(overall_limit=None),
        _category_spending("1500"),
        total_expense=Decimal("2000"),
        local_today=date(2026, 8, 10),
    )

    overall = result.overall
    assert overall.spent_amount == Decimal("2000.0000")
    assert overall.daily_burn_rate == Decimal("200.0000")
    assert overall.limit_amount is None
    assert overall.remaining_allowance is None
    assert overall.pace_projected_spend is None
    assert overall.risk_level is BudgetRiskLevel.UNAVAILABLE
    assert overall.warning_status is BudgetWarningStatus.UNAVAILABLE
    assert result.categories[0].performance.limit_amount == Decimal("3000.0000")


def test_zero_spending_returns_exact_zero_metrics() -> None:
    result = evaluate_budget(
        _definition(),
        (),
        total_expense=Decimal("0"),
        local_today=date(2026, 8, 1),
    )

    assert result.overall.daily_burn_rate == Decimal("0.0000")
    assert result.overall.pace_projected_spend == Decimal("0.0000")
    assert result.categories[0].transaction_count == 0
    assert result.categories[0].performance.spent_amount == Decimal("0.0000")


def test_policy_rejects_future_invalid_or_cross_limit_evidence() -> None:
    with pytest.raises(ValueError, match="before its start"):
        evaluate_budget(
            _definition(),
            (),
            total_expense=Decimal("0"),
            local_today=date(2026, 7, 31),
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        evaluate_budget(
            _definition(),
            (),
            total_expense=Decimal("-1"),
            local_today=date(2026, 8, 1),
        )
    with pytest.raises(ValueError, match="configured limit"):
        evaluate_budget(
            _definition(),
            _category_spending("10", category_id=uuid4()),
            total_expense=Decimal("10"),
            local_today=date(2026, 8, 1),
        )
    with pytest.raises(ValueError, match="cannot exceed total"):
        evaluate_budget(
            _definition(),
            _category_spending("20"),
            total_expense=Decimal("10"),
            local_today=date(2026, 8, 1),
        )
    with pytest.raises(ValueError, match="at least one day"):
        evaluate_budget(
            _definition(start=date(2026, 8, 31), end=date(2026, 8, 1)),
            (),
            total_expense=Decimal("0"),
            local_today=date(2026, 8, 31),
        )
    with pytest.raises(ValueError, match="cannot exceed 366"):
        evaluate_budget(
            _definition(start=date(2025, 1, 1), end=date(2026, 8, 1)),
            (),
            total_expense=Decimal("0"),
            local_today=date(2026, 8, 1),
        )


def test_archived_timestamp_does_not_change_historical_math() -> None:
    definition = _definition()
    archived = BudgetDefinition(
        budget_id=definition.budget_id,
        name=definition.name,
        period_start_date=definition.period_start_date,
        period_end_date=definition.period_end_date,
        currency=definition.currency,
        overall_limit=definition.overall_limit,
        archived_at=datetime(2026, 9, 1, tzinfo=UTC),
        category_limits=definition.category_limits,
    )

    result = evaluate_budget(
        archived,
        _category_spending("100"),
        total_expense=Decimal("100"),
        local_today=date(2026, 9, 1),
    )

    assert result.status is BudgetAnalysisStatus.COMPLETED
    assert result.overall.spent_amount == Decimal("100.0000")
