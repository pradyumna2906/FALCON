"""Exact Phase 10 contribution-progress policy tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.goal_planning import (
    GoalFundingState,
    calculate_goal_progress,
    months_until_deadline,
)
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _goal(
    *,
    starting: str = "1000",
    target: str = "10000",
    status: GoalStatus = GoalStatus.ACTIVE,
    target_date: date = date(2027, 3, 14),
) -> Goal:
    return Goal(
        id=uuid4(),
        user_id=uuid4(),
        name="Travel",
        goal_type=GoalType.TRAVEL,
        target_amount=Decimal(target),
        starting_amount=Decimal(starting),
        currency="INR",
        target_date=target_date,
        priority=GoalPriority.HIGH,
        status=status,
        description=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_progress_uses_exact_amounts_ratio_and_ceiling_monthly_need() -> None:
    result = calculate_goal_progress(
        goal=_goal(),
        contribution_amount=Decimal("2000.0000"),
        calculated_on=date(2026, 9, 14),
    )

    assert result.current_amount == Decimal("3000.0000")
    assert result.remaining_amount == Decimal("7000.0000")
    assert result.funding_ratio == Decimal("0.300000")
    assert result.funding_percentage == Decimal("30.0000")
    assert result.months_remaining == 6
    assert result.required_monthly_contribution == Decimal("1166.6667")
    assert result.funding_state is GoalFundingState.IN_PROGRESS


@pytest.mark.parametrize(
    ("starting", "contributed", "status", "expected"),
    [
        ("0", "0", GoalStatus.ACTIVE, GoalFundingState.NOT_STARTED),
        ("10000", "0", GoalStatus.ACTIVE, GoalFundingState.FUNDED),
        ("1000", "9000", GoalStatus.COMPLETED, GoalFundingState.COMPLETED),
        ("1000", "0", GoalStatus.CANCELLED, GoalFundingState.CANCELLED),
        ("1000", "0", GoalStatus.ACTIVE, GoalFundingState.IN_PROGRESS),
    ],
)
def test_progress_exposes_funding_and_terminal_states(
    starting: str,
    contributed: str,
    status: GoalStatus,
    expected: GoalFundingState,
) -> None:
    result = calculate_goal_progress(
        goal=_goal(starting=starting, status=status),
        contribution_amount=Decimal(contributed),
        calculated_on=date(2026, 9, 14),
    )

    assert result.funding_state is expected


def test_progress_caps_overfunded_ratio_and_required_amount() -> None:
    result = calculate_goal_progress(
        goal=_goal(starting="9000"),
        contribution_amount=Decimal("2000"),
        calculated_on=date(2026, 9, 14),
    )

    assert result.current_amount == Decimal("11000.0000")
    assert result.remaining_amount == Decimal("0.0000")
    assert result.funding_ratio == Decimal("1.000000")
    assert result.required_monthly_contribution == Decimal("0.0000")


def test_progress_marks_an_unfunded_past_deadline_overdue() -> None:
    result = calculate_goal_progress(
        goal=_goal(target_date=date(2026, 9, 14)),
        contribution_amount=Decimal("0"),
        calculated_on=date(2026, 9, 14),
    )

    assert result.months_remaining == 0
    assert result.funding_state is GoalFundingState.OVERDUE


@pytest.mark.parametrize(
    ("calculated_on", "target_date", "expected"),
    [
        (date(2026, 9, 14), date(2026, 10, 1), 1),
        (date(2026, 9, 14), date(2026, 10, 15), 2),
        (date(2026, 9, 14), date(2026, 9, 14), 0),
    ],
)
def test_months_until_deadline_uses_calendar_deposit_periods(
    calculated_on: date,
    target_date: date,
    expected: int,
) -> None:
    assert months_until_deadline(
        calculated_on=calculated_on,
        target_date=target_date,
    ) == expected


def test_progress_rejects_invalid_internal_evidence() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        calculate_goal_progress(
            goal=_goal(),
            contribution_amount=Decimal("-1"),
            calculated_on=date(2026, 9, 14),
        )
