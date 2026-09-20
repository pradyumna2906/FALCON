"""Tests for deterministic Phase 11 standard paths and ordered shocks."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from falcon_api.scenario_simulation import (
    DebtPaymentAdjustment,
    IncomeInterruptionAssumption,
    OneTimeExpenseAssumption,
    RecurringExpenseAdjustment,
    ScenarioAssumptions,
    ScenarioCaseKind,
    ScenarioPathStatus,
    ScenarioReasonCode,
    build_deterministic_scenario_paths,
)
from scenario_test_data import transient_scenario_snapshot


def _stress_case() -> ScenarioAssumptions:
    return ScenarioAssumptions(
        name="Income and expense stress",
        income_change_percent=Decimal("-20"),
        expense_change_percent=Decimal("10"),
        one_time_expenses=(
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal("10"),
            ),
        ),
        recurring_expense_adjustments=(
            RecurringExpenseAdjustment(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 11, 1),
                monthly_delta=Decimal("5"),
            ),
        ),
        debt_payment_adjustments=(
            DebtPaymentAdjustment(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 11, 1),
                monthly_delta=Decimal("2"),
            ),
        ),
        income_interruptions=(
            IncomeInterruptionAssumption(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 10, 1),
                retained_income_percent=Decimal("50"),
            ),
        ),
        emergency_fund_target_months=Decimal("2"),
    )


def test_standard_paths_use_exact_protected_expected_and_upside_bands() -> None:
    snapshot = transient_scenario_snapshot((_stress_case(),))

    paths = build_deterministic_scenario_paths(snapshot)

    assert [item.kind for item in paths[:3]] == [
        ScenarioCaseKind.PROTECTED,
        ScenarioCaseKind.EXPECTED,
        ScenarioCaseKind.UPSIDE,
    ]
    assert paths[0].selected_total == Decimal("100.0000")
    assert paths[1].selected_total == Decimal("150.0000")
    assert paths[2].selected_total == Decimal("200.0000")
    assert paths[0].periods[0].selected_capacity == Decimal("50.0000")
    assert paths[1].periods[0].selected_capacity == Decimal("75.0000")
    assert paths[2].periods[0].selected_capacity == Decimal("100.0000")
    assert build_deterministic_scenario_paths(snapshot) == paths
    assert len({item.path_id for item in paths}) == len(paths)


def test_user_path_applies_shocks_once_in_the_documented_order() -> None:
    snapshot = transient_scenario_snapshot((_stress_case(),))

    path = build_deterministic_scenario_paths(snapshot)[3]

    assert path.status is ScenarioPathStatus.AVAILABLE
    assert path.protected_total == Decimal("20.5000")
    assert path.expected_total == Decimal("51.0000")
    assert path.upside_total == Decimal("101.0000")
    october, november = path.periods
    assert october.income_delta == Decimal("-45.0000")
    assert november.income_delta == Decimal("-15.0000")
    assert october.expense_delta == Decimal("7.5000")
    assert october.one_time_expense == Decimal("10.0000")
    assert october.recurring_expense_delta == Decimal("5.0000")
    assert october.debt_payment_delta == Decimal("2.0000")
    assert october.raw_protected_amount == Decimal("-19.5000")
    assert october.protected_amount == Decimal("0.0000")
    assert november.protected_amount == Decimal("20.5000")
    assert path.emergency_reserve_amount == Decimal("175.0000")
    assert ScenarioReasonCode.NEGATIVE_CAPACITY_CLIPPED in path.reason_codes
    assert ScenarioReasonCode.EMERGENCY_RESERVE_RECALCULATED in path.reason_codes


def test_missing_required_supplemental_evidence_fails_closed() -> None:
    snapshot = transient_scenario_snapshot(
        (_stress_case(),),
        include_supplemental=False,
    )

    path = build_deterministic_scenario_paths(snapshot)[3]

    assert path.status is ScenarioPathStatus.UNAVAILABLE
    assert path.periods == ()
    assert ScenarioReasonCode.INCOME_FORECAST_REQUIRED in path.reason_codes
    assert ScenarioReasonCode.EXPENSE_FORECAST_REQUIRED in path.reason_codes


def test_missing_savings_forecast_only_permits_limited_protected_evidence() -> None:
    snapshot = replace(
        transient_scenario_snapshot(
            (
                ScenarioAssumptions(
                    name="Known one-time expense",
                    one_time_expenses=(
                        OneTimeExpenseAssumption(
                            period_start=date(2026, 10, 1),
                            amount=Decimal("10"),
                        ),
                    ),
                ),
            )
        ),
        forecast=None,
    )

    protected, expected, upside, user = build_deterministic_scenario_paths(snapshot)

    assert protected.status is ScenarioPathStatus.LIMITED
    assert protected.selected_total == Decimal("100.0000")
    assert expected.status is ScenarioPathStatus.UNAVAILABLE
    assert upside.status is ScenarioPathStatus.UNAVAILABLE
    assert user.status is ScenarioPathStatus.LIMITED
    assert user.selected_total == Decimal("90.0000")
    for path in (protected, expected, upside, user):
        assert ScenarioReasonCode.SOURCE_SAVINGS_FORECAST_MISSING in path.reason_codes
