"""Deterministic protected-capacity greedy allocation baseline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from falcon_api.analytics.types import money
from falcon_api.goal_planning.progress import GoalProgress
from falcon_api.goal_planning.ranking import GoalRanking
from falcon_api.goal_planning.snapshot import GoalPlanningSnapshot


GREEDY_ALLOCATION_POLICY_VERSION = "2026.1"


class GreedyBaselineWarning(StrEnum):
    """Stable limitations or outcomes of the reference allocation."""

    CAPACITY_MISSING = "capacity_missing"
    CAPACITY_PROVISIONAL = "capacity_provisional"
    SNAPSHOT_EVIDENCE_INCOMPLETE = "snapshot_evidence_incomplete"
    NO_ELIGIBLE_GOALS = "no_eligible_goals"
    CAPACITY_LEFT_UNALLOCATED = "capacity_left_unallocated"
    GOALS_REMAIN_UNFUNDED = "goals_remain_unfunded"


@dataclass(frozen=True, slots=True)
class GoalMonthlyAllocation:
    """One exact, non-persistent assignment in a forecast month."""

    goal_id: UUID
    rank: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class MonthlyAllocationPeriod:
    """Protected capacity consumed at most once in one month."""

    period_start: date
    available_capacity: Decimal
    allocated_amount: Decimal
    unallocated_amount: Decimal
    allocations: tuple[GoalMonthlyAllocation, ...]


@dataclass(frozen=True, slots=True)
class GoalAllocationProjection:
    """Projected goal outcome produced by an exact allocation schedule."""

    goal_id: UUID
    rank: int
    starting_remaining_amount: Decimal
    allocated_amount: Decimal
    projected_remaining_amount: Decimal
    projected_completion_period: date | None
    deadline_met: bool


# Preserve the public Batch 3 name while making the shared type strategy-neutral.
GoalBaselineProjection = GoalAllocationProjection


@dataclass(frozen=True, slots=True)
class GreedyAllocationBaseline:
    """Immutable reference plan used to evaluate the later solver."""

    baseline_id: str
    snapshot_id: str
    policy_version: str
    ranking_policy_version: str
    capacity_policy_version: str | None
    allocation_band: str
    currency: str
    periods: tuple[MonthlyAllocationPeriod, ...]
    goal_projections: tuple[GoalBaselineProjection, ...]
    capacity_total: Decimal
    allocated_total: Decimal
    unallocated_total: Decimal
    warnings: tuple[GreedyBaselineWarning, ...]


def build_greedy_allocation_baseline(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
) -> GreedyAllocationBaseline:
    """Allocate protected monthly capacity by rank without database mutation."""
    validate_allocation_inputs(snapshot=snapshot, ranking=ranking)
    goals = {goal.goal_id: goal for goal in snapshot.goals}
    remaining = {
        goal_id: money(goal.remaining_amount) for goal_id, goal in goals.items()
    }
    allocated = {goal_id: Decimal("0.0000") for goal_id in goals}
    completion: dict[UUID, date | None] = {
        goal_id: (snapshot.local_date if amount == 0 else None)
        for goal_id, amount in remaining.items()
    }
    points = (
        tuple(
            sorted(
                snapshot.savings_capacity.points,
                key=lambda item: item.period_start,
            )
        )
        if snapshot.savings_capacity is not None
        else ()
    )
    periods: list[MonthlyAllocationPeriod] = []
    for point in points:
        available = money(point.protected_amount)
        month_allocations: list[GoalMonthlyAllocation] = []
        for ranked in ranking.items:
            goal = goals[ranked.goal_id]
            if (
                available == 0
                or not ranked.eligible_for_allocation
                or point.period_start > goal.target_date
                or remaining[goal.goal_id] == 0
            ):
                continue
            amount = money(min(available, remaining[goal.goal_id]))
            remaining[goal.goal_id] = money(remaining[goal.goal_id] - amount)
            allocated[goal.goal_id] = money(allocated[goal.goal_id] + amount)
            available = money(available - amount)
            month_allocations.append(
                GoalMonthlyAllocation(
                    goal_id=goal.goal_id,
                    rank=ranked.rank,
                    amount=amount,
                )
            )
            if remaining[goal.goal_id] == 0:
                completion[goal.goal_id] = point.period_start
        period_allocated = money(point.protected_amount - available)
        periods.append(
            MonthlyAllocationPeriod(
                period_start=point.period_start,
                available_capacity=money(point.protected_amount),
                allocated_amount=period_allocated,
                unallocated_amount=available,
                allocations=tuple(month_allocations),
            )
        )

    projections = tuple(
        _projection(
            goal=goals[item.goal_id],
            rank=item.rank,
            allocated=allocated[item.goal_id],
            remaining=remaining[item.goal_id],
            completion=completion[item.goal_id],
        )
        for item in ranking.items
    )
    capacity_total = money(
        sum((period.available_capacity for period in periods), Decimal("0"))
    )
    allocated_total = money(
        sum((period.allocated_amount for period in periods), Decimal("0"))
    )
    unallocated_total = money(capacity_total - allocated_total)
    warnings = _warnings(
        capacity_present=snapshot.savings_capacity is not None,
        capacity_reliability=(
            snapshot.savings_capacity.reliability
            if snapshot.savings_capacity is not None
            else None
        ),
        snapshot_has_warnings=bool(snapshot.warnings),
        ranking=ranking,
        projections=projections,
        unallocated_total=unallocated_total,
    )
    baseline_id = _baseline_id(
        snapshot_id=snapshot.snapshot_id,
        ranking=ranking,
        periods=tuple(periods),
    )
    return GreedyAllocationBaseline(
        baseline_id=baseline_id,
        snapshot_id=snapshot.snapshot_id,
        policy_version=GREEDY_ALLOCATION_POLICY_VERSION,
        ranking_policy_version=ranking.policy_version,
        capacity_policy_version=(
            snapshot.savings_capacity.policy_version
            if snapshot.savings_capacity is not None
            else None
        ),
        allocation_band="protected_95_percent_lower",
        currency=snapshot.currency,
        periods=tuple(periods),
        goal_projections=projections,
        capacity_total=capacity_total,
        allocated_total=allocated_total,
        unallocated_total=unallocated_total,
        warnings=warnings,
    )


def validate_allocation_inputs(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
) -> None:
    if ranking.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Ranking and planning snapshot identifiers must match.")
    goal_by_id = {goal.goal_id: goal for goal in snapshot.goals}
    goal_ids = set(goal_by_id)
    if len(goal_ids) != len(snapshot.goals):
        raise ValueError("Snapshot goals must be unique.")
    ranked_ids = [item.goal_id for item in ranking.items]
    if len(set(ranked_ids)) != len(ranked_ids) or set(ranked_ids) != goal_ids:
        raise ValueError("Ranking must contain every snapshot goal exactly once.")
    if [item.rank for item in ranking.items] != list(range(1, len(ranking.items) + 1)):
        raise ValueError("Ranking positions must be contiguous and ordered.")
    for item in ranking.items:
        goal = goal_by_id[item.goal_id]
        if not goal.remaining_amount.is_finite() or goal.remaining_amount < 0:
            raise ValueError("Goal remaining amounts must be finite and non-negative.")
        expected_eligibility = (
            goal.remaining_amount > 0 and goal.target_date > goal.calculated_on
        )
        if item.eligible_for_allocation is not expected_eligibility:
            raise ValueError("Ranking allocation eligibility must match the snapshot.")
    capacity = snapshot.savings_capacity
    if capacity is None:
        return
    if capacity.currency != snapshot.currency:
        raise ValueError("Savings capacity and snapshot currencies must match.")
    periods = [point.period_start for point in capacity.points]
    if len(set(periods)) != len(periods):
        raise ValueError("Savings capacity periods must be unique.")
    if any(period < snapshot.local_date for period in periods):
        raise ValueError(
            "Goal allocation cannot use capacity before the snapshot date."
        )
    if any(not point.protected_amount.is_finite() for point in capacity.points):
        raise ValueError("Protected savings capacity must be finite.")
    if any(point.protected_amount < 0 for point in capacity.points):
        raise ValueError("Protected savings capacity must be non-negative.")
    if not capacity.protected_total.is_finite():
        raise ValueError("Protected savings capacity total must be finite.")
    point_total = money(
        sum((point.protected_amount for point in capacity.points), Decimal("0"))
    )
    if money(capacity.protected_total) != point_total:
        raise ValueError("Protected savings capacity total must match its periods.")


def _projection(
    *,
    goal: GoalProgress,
    rank: int,
    allocated: Decimal,
    remaining: Decimal,
    completion: date | None,
) -> GoalBaselineProjection:
    return GoalBaselineProjection(
        goal_id=goal.goal_id,
        rank=rank,
        starting_remaining_amount=money(goal.remaining_amount),
        allocated_amount=money(allocated),
        projected_remaining_amount=money(remaining),
        projected_completion_period=completion,
        deadline_met=(completion is not None and completion <= goal.target_date),
    )


def _warnings(
    *,
    capacity_present: bool,
    capacity_reliability: str | None,
    snapshot_has_warnings: bool,
    ranking: GoalRanking,
    projections: tuple[GoalBaselineProjection, ...],
    unallocated_total: Decimal,
) -> tuple[GreedyBaselineWarning, ...]:
    warnings: list[GreedyBaselineWarning] = []
    if not capacity_present:
        warnings.append(GreedyBaselineWarning.CAPACITY_MISSING)
    elif capacity_reliability == "provisional":
        warnings.append(GreedyBaselineWarning.CAPACITY_PROVISIONAL)
    if snapshot_has_warnings:
        warnings.append(GreedyBaselineWarning.SNAPSHOT_EVIDENCE_INCOMPLETE)
    if not any(item.eligible_for_allocation for item in ranking.items):
        warnings.append(GreedyBaselineWarning.NO_ELIGIBLE_GOALS)
    if unallocated_total > 0:
        warnings.append(GreedyBaselineWarning.CAPACITY_LEFT_UNALLOCATED)
    if any(
        item.starting_remaining_amount > 0
        and item.projected_remaining_amount > 0
        for item in projections
    ):
        warnings.append(GreedyBaselineWarning.GOALS_REMAIN_UNFUNDED)
    return tuple(warnings)


def _baseline_id(
    *,
    snapshot_id: str,
    ranking: GoalRanking,
    periods: tuple[MonthlyAllocationPeriod, ...],
) -> str:
    payload = {
        "snapshot_id": snapshot_id,
        "ranking_policy_version": ranking.policy_version,
        "allocation_policy_version": GREEDY_ALLOCATION_POLICY_VERSION,
        "periods": [
            {
                "period_start": period.period_start.isoformat(),
                "capacity": str(period.available_capacity),
                "allocations": [
                    {
                        "goal_id": str(allocation.goal_id),
                        "rank": allocation.rank,
                        "amount": str(allocation.amount),
                    }
                    for allocation in period.allocations
                ],
            }
            for period in periods
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
