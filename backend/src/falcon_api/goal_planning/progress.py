"""Exact contribution-aware progress calculations for financial goals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from uuid import UUID

from falcon_api.analytics.types import MONEY_QUANTUM, money
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


PROGRESS_RATIO_QUANTUM = Decimal("0.000001")


class GoalFundingState(StrEnum):
    """Contribution-aware state without changing the stored goal lifecycle."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    FUNDED = "funded"
    OVERDUE = "overdue"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class GoalProgress:
    """Exact progress evidence for one goal at one trusted local date."""

    goal_id: UUID
    goal_name: str
    goal_type: GoalType
    priority: GoalPriority
    target_date: date
    currency: str
    target_amount: Decimal
    starting_amount: Decimal
    contribution_amount: Decimal
    current_amount: Decimal
    remaining_amount: Decimal
    funding_ratio: Decimal
    funding_percentage: Decimal
    months_remaining: int
    required_monthly_contribution: Decimal
    funding_state: GoalFundingState
    calculated_on: date


def calculate_goal_progress(
    *,
    goal: Goal,
    contribution_amount: Decimal,
    calculated_on: date,
) -> GoalProgress:
    """Calculate bounded progress using Decimal values only."""
    target = money(goal.target_amount)
    starting = money(goal.starting_amount)
    contributed = money(contribution_amount)
    if target <= 0 or starting < 0 or contributed < 0:
        raise ValueError("Goal progress inputs must be non-negative and valid.")

    current = money(starting + contributed)
    remaining = money(max(Decimal("0"), target - current))
    ratio = min(Decimal("1"), current / target).quantize(
        PROGRESS_RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
    months = months_until_deadline(
        calculated_on=calculated_on,
        target_date=goal.target_date,
    )
    required = (
        Decimal("0.0000")
        if remaining == 0 or months == 0
        else (remaining / Decimal(months)).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_CEILING,
        )
    )
    return GoalProgress(
        goal_id=goal.id,
        goal_name=goal.name,
        goal_type=GoalType(goal.goal_type),
        priority=GoalPriority(goal.priority),
        target_date=goal.target_date,
        currency=goal.currency,
        target_amount=target,
        starting_amount=starting,
        contribution_amount=contributed,
        current_amount=current,
        remaining_amount=remaining,
        funding_ratio=ratio,
        funding_percentage=(ratio * Decimal("100")).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_EVEN,
        ),
        months_remaining=months,
        required_monthly_contribution=required,
        funding_state=_funding_state(
            status=GoalStatus(goal.status),
            current=current,
            target=target,
            months_remaining=months,
        ),
        calculated_on=calculated_on,
    )


def months_until_deadline(*, calculated_on: date, target_date: date) -> int:
    """Return the number of monthly deposits available through the deadline."""
    if target_date <= calculated_on:
        return 0
    months = (
        (target_date.year - calculated_on.year) * 12
        + target_date.month
        - calculated_on.month
    )
    if target_date.day > calculated_on.day:
        months += 1
    return max(1, months)


def _funding_state(
    *,
    status: GoalStatus,
    current: Decimal,
    target: Decimal,
    months_remaining: int,
) -> GoalFundingState:
    if status is GoalStatus.COMPLETED:
        return GoalFundingState.COMPLETED
    if status is GoalStatus.CANCELLED:
        return GoalFundingState.CANCELLED
    if current < target and months_remaining == 0:
        return GoalFundingState.OVERDUE
    if current <= 0:
        return GoalFundingState.NOT_STARTED
    if current >= target:
        return GoalFundingState.FUNDED
    return GoalFundingState.IN_PROGRESS
