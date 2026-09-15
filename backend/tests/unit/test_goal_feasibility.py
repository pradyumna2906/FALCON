"""Checkpoint 10.6 feasibility and deadline-risk policy tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.goal_planning import (
    FEASIBILITY_POLICY_VERSION,
    FeasibilityEvidenceReliability,
    GoalDeadlineRiskLevel,
    GoalFeasibilityReasonCode,
    GoalFeasibilityState,
    SavingsCapacityPlan,
    SavingsCapacityPoint,
    assess_goal_feasibility,
    assess_snapshot_feasibility,
    calculate_goal_progress,
)
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def _progress(
    *,
    target: str = "10000",
    starting: str = "0",
    contribution: str = "0",
    deadline: date = date(2026, 11, 30),
):
    goal = Goal(
        id=uuid4(),
        user_id=uuid4(),
        name="Education",
        goal_type=GoalType.EDUCATION,
        target_amount=Decimal(target),
        starting_amount=Decimal(starting),
        currency="INR",
        target_date=deadline,
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
        description=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return calculate_goal_progress(
        goal=goal,
        contribution_amount=Decimal(contribution),
        calculated_on=date(2026, 9, 15),
    )


def _capacity(
    *,
    rows: tuple[tuple[date, str, str, str], ...] = (
        (date(2026, 10, 1), "500", "900", "1500"),
        (date(2026, 11, 1), "500", "900", "1500"),
    ),
    currency: str = "INR",
    reliability: str = "normal",
) -> SavingsCapacityPlan:
    points = tuple(
        SavingsCapacityPoint(
            period_start=period,
            protected_amount=Decimal(protected),
            expected_amount=Decimal(expected),
            upside_amount=Decimal(upside),
        )
        for period, protected, expected, upside in rows
    )
    return SavingsCapacityPlan(
        forecast_run_id=uuid4(),
        currency=currency,
        policy_version="2026.1",
        protection_band="95_percent",
        reliability=reliability,
        points=points,
        protected_total=sum((item.protected_amount for item in points), Decimal(0)),
        expected_total=sum((item.expected_amount for item in points), Decimal(0)),
        upside_total=sum((item.upside_amount for item in points), Decimal(0)),
    )


def test_secure_goal_uses_protected_capacity_and_completion_window() -> None:
    result = assess_goal_feasibility(
        _progress(target="900"),
        _capacity(),
    )

    assert result.policy_version == FEASIBILITY_POLICY_VERSION == "2026.1"
    assert result.feasibility_state is GoalFeasibilityState.SECURE
    assert result.deadline_risk is GoalDeadlineRiskLevel.LOW
    assert result.completion_probability == Decimal("0.975000")
    assert result.protected_capacity_by_deadline == Decimal("1000.0000")
    assert result.protected_shortfall == Decimal("0.0000")
    assert result.completion_window.protected_period == date(2026, 11, 1)
    assert result.reason_codes[-1] is (
        GoalFeasibilityReasonCode.PROTECTED_CAPACITY_SUFFICIENT
    )


def test_expected_and_upside_ranges_produce_interpolated_probabilities() -> None:
    expected = assess_goal_feasibility(_progress(target="1400"), _capacity())
    stretch = assess_goal_feasibility(_progress(target="2400"), _capacity())

    assert expected.feasibility_state is GoalFeasibilityState.FEASIBLE
    assert expected.deadline_risk is GoalDeadlineRiskLevel.MODERATE
    assert Decimal("0.5") < expected.completion_probability < Decimal("0.975")
    assert expected.expected_shortfall == Decimal("0.0000")
    assert stretch.feasibility_state is GoalFeasibilityState.STRETCH
    assert stretch.deadline_risk is GoalDeadlineRiskLevel.HIGH
    assert Decimal("0") < stretch.completion_probability < Decimal("0.5")
    assert stretch.reason_codes[-1] is (
        GoalFeasibilityReasonCode.UPSIDE_CAPACITY_REQUIRED
    )


def test_covered_horizon_marks_upside_shortfall_unlikely() -> None:
    result = assess_goal_feasibility(_progress(target="4000"), _capacity())

    assert result.feasibility_state is GoalFeasibilityState.UNLIKELY
    assert result.deadline_risk is GoalDeadlineRiskLevel.CRITICAL
    assert result.completion_probability == Decimal("0.000000")
    assert result.upside_shortfall == Decimal("1000.0000")


def test_short_forecast_horizon_is_indeterminate_not_false_failure() -> None:
    result = assess_goal_feasibility(
        _progress(target="4000", deadline=date(2027, 3, 31)),
        _capacity(),
    )

    assert result.feasibility_state is GoalFeasibilityState.INDETERMINATE
    assert result.deadline_risk is GoalDeadlineRiskLevel.UNKNOWN
    assert result.completion_probability is None
    assert result.evidence_reliability is (
        FeasibilityEvidenceReliability.LIMITED_HORIZON
    )
    assert GoalFeasibilityReasonCode.FORECAST_HORIZON_BEFORE_DEADLINE in (
        result.reason_codes
    )


def test_forecast_starting_after_deadline_is_explicitly_unlikely() -> None:
    result = assess_goal_feasibility(
        _progress(target="100", deadline=date(2026, 9, 30)),
        _capacity(
            rows=((date(2026, 10, 1), "500", "900", "1500"),),
        ),
    )

    assert result.feasibility_state is GoalFeasibilityState.UNLIKELY
    assert result.completion_probability == Decimal("0.000000")
    assert GoalFeasibilityReasonCode.FORECAST_STARTS_AFTER_DEADLINE in (
        result.reason_codes
    )


def test_missing_capacity_and_provisional_forecast_are_not_hidden() -> None:
    unavailable = assess_goal_feasibility(_progress(), None)
    provisional = assess_goal_feasibility(
        _progress(target="1400"),
        _capacity(reliability="provisional"),
    )

    assert unavailable.feasibility_state is GoalFeasibilityState.UNAVAILABLE
    assert unavailable.completion_probability is None
    assert unavailable.evidence_reliability is (
        FeasibilityEvidenceReliability.UNAVAILABLE
    )
    assert provisional.evidence_reliability is (
        FeasibilityEvidenceReliability.PROVISIONAL
    )
    assert GoalFeasibilityReasonCode.FORECAST_PROVISIONAL in provisional.reason_codes


def test_funded_and_overdue_goals_have_terminal_assessment_evidence() -> None:
    funded = assess_goal_feasibility(
        _progress(target="1000", starting="1000"),
        _capacity(),
    )
    overdue = assess_goal_feasibility(
        _progress(deadline=date(2026, 9, 15)),
        _capacity(),
    )

    assert funded.feasibility_state is GoalFeasibilityState.FUNDED
    assert funded.completion_probability == Decimal("1.000000")
    assert funded.completion_window.expected_period == date(2026, 9, 15)
    assert overdue.feasibility_state is GoalFeasibilityState.OVERDUE
    assert overdue.deadline_risk is GoalDeadlineRiskLevel.OVERDUE
    assert overdue.completion_probability == Decimal("0.000000")


def test_snapshot_assessment_preserves_goal_order() -> None:
    first = _progress(target="1000")
    second = _progress(target="2000")

    results = assess_snapshot_feasibility((first, second), _capacity())

    assert tuple(item.goal_id for item in results) == (first.goal_id, second.goal_id)


@pytest.mark.parametrize(
    ("capacity", "message"),
    [
        (_capacity(currency="USD"), "currencies"),
        (
            _capacity(
                rows=(
                    (date(2026, 10, 1), "1", "2", "3"),
                    (date(2026, 10, 1), "1", "2", "3"),
                )
            ),
            "unique",
        ),
        (
            _capacity(rows=((date(2026, 10, 1), "10", "5", "20"),)),
            "ordered",
        ),
    ],
)
def test_feasibility_rejects_incompatible_capacity(
    capacity: SavingsCapacityPlan,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        assess_goal_feasibility(_progress(), capacity)
