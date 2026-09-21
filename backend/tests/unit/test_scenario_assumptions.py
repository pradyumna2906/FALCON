"""Tests for bounded immutable Phase 11 assumption contracts."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from falcon_api.models.enums import GoalPriority
from falcon_api.scenario_simulation import (
    DebtPaymentAdjustment,
    GoalScenarioAdjustment,
    IncomeInterruptionAssumption,
    OneTimeExpenseAssumption,
    RecurringExpenseAdjustment,
    ScenarioAssumptions,
    validate_scenario_assumptions,
)


GOAL_ID = UUID("20000000-0000-4000-8000-000000000001")


def test_complete_scenario_normalizes_exact_values() -> None:
    scenario = ScenarioAssumptions(
        name="  Income shock  ",
        income_change_percent=Decimal("-10"),
        expense_change_percent=Decimal("5"),
        one_time_expenses=(
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal("1000.12345"),
            ),
        ),
        recurring_expense_adjustments=(
            RecurringExpenseAdjustment(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 11, 1),
                monthly_delta=Decimal("250"),
            ),
        ),
        debt_payment_adjustments=(
            DebtPaymentAdjustment(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 11, 1),
                monthly_delta=Decimal("50"),
            ),
        ),
        income_interruptions=(
            IncomeInterruptionAssumption(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 10, 1),
                retained_income_percent=Decimal("25"),
            ),
        ),
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                target_amount=Decimal("125"),
                target_date=date(2027, 1, 31),
                priority=GoalPriority.CRITICAL,
                monthly_contribution_delta=Decimal("10"),
                pause_start=date(2026, 11, 1),
                pause_end=date(2026, 11, 1),
            ),
        ),
        emergency_fund_target_months=Decimal("6"),
    )

    assert scenario.name == "Income shock"
    assert scenario.income_change_percent == Decimal("-10.0000")
    assert scenario.one_time_expenses[0].amount == Decimal("1000.1234")
    assert scenario.goal_adjustments[0].priority is GoalPriority.CRITICAL
    assert scenario.debt_payment_adjustments[0].monthly_delta == Decimal("50.0000")
    assert scenario.has_override is True


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: ScenarioAssumptions(name="Empty"),
            "at least one override",
        ),
        (
            lambda: ScenarioAssumptions(
                name="Bad percent", income_change_percent=Decimal("301")
            ),
            "between -100 and 300",
        ),
        (
            lambda: OneTimeExpenseAssumption(
                period_start=date(2026, 10, 2), amount=Decimal("1")
            ),
            "month boundary",
        ),
        (
            lambda: RecurringExpenseAdjustment(
                start_period=date(2026, 11, 1),
                end_period=date(2026, 10, 1),
                monthly_delta=Decimal("1"),
            ),
            "cannot precede",
        ),
        (
            lambda: IncomeInterruptionAssumption(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 10, 1),
                retained_income_percent=Decimal("101"),
            ),
            "between 0 and 100",
        ),
        (
            lambda: DebtPaymentAdjustment(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 11, 1),
                monthly_delta=Decimal("0"),
            ),
            "cannot be zero",
        ),
        (
            lambda: GoalScenarioAdjustment(goal_id=GOAL_ID),
            "at least one value",
        ),
        (
            lambda: GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                monthly_contribution_delta=Decimal("0"),
            ),
            "cannot be zero",
        ),
    ],
)
def test_invalid_assumptions_fail_closed(factory, message) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_scenario_set_requires_unique_bounded_names_and_goals() -> None:
    first = ScenarioAssumptions(name="Stress", income_change_percent=Decimal("-10"))
    second = ScenarioAssumptions(name="stress", expense_change_percent=Decimal("10"))
    with pytest.raises(ValueError, match="unique"):
        validate_scenario_assumptions((first, second))
    with pytest.raises(ValueError, match="between 1 and 10"):
        validate_scenario_assumptions(())

    duplicate_goal = GoalScenarioAdjustment(
        goal_id=uuid4(),
        target_date=date(2027, 1, 1),
    )
    with pytest.raises(ValueError, match="at most once"):
        ScenarioAssumptions(
            name="Duplicate goals",
            goal_adjustments=(duplicate_goal, duplicate_goal),
        )

    with pytest.raises(ValueError, match="cannot overlap"):
        ScenarioAssumptions(
            name="Overlapping interruption",
            income_interruptions=(
                IncomeInterruptionAssumption(
                    start_period=date(2026, 10, 1),
                    end_period=date(2026, 11, 1),
                ),
                IncomeInterruptionAssumption(
                    start_period=date(2026, 11, 1),
                    end_period=date(2026, 12, 1),
                ),
            ),
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal("NaN"),
            ),
            "finite and bounded",
        ),
        (
            lambda: OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal("-1"),
            ),
            "must be positive",
        ),
        (
            lambda: RecurringExpenseAdjustment(
                start_period=date(2026, 1, 1),
                end_period=date(2028, 1, 1),
                monthly_delta=Decimal("1"),
            ),
            "supported horizon",
        ),
        (
            lambda: GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                pause_start=date(2026, 10, 1),
            ),
            "both start and end",
        ),
        (
            lambda: ScenarioAssumptions(
                name="\n",
                income_change_percent=Decimal("1"),
            ),
            "printable",
        ),
        (
            lambda: ScenarioAssumptions(
                name="Emergency",
                emergency_fund_target_months=Decimal("25"),
            ),
            "between 0 and 24",
        ),
        (
            lambda: ScenarioAssumptions(
                name="Too many events",
                one_time_expenses=tuple(
                    OneTimeExpenseAssumption(
                        period_start=date(2026, 10, 1),
                        amount=Decimal("1"),
                    )
                    for _ in range(13)
                ),
            ),
            "supported limit of 12",
        ),
    ],
)
def test_additional_financial_and_size_boundaries(factory, message) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
