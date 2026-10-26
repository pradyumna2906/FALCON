"""Unified safe schedule selection and baseline comparison for Phase 10."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from falcon_api.analytics.types import money
from falcon_api.goal_planning.analysis import (
    GoalPlanningAnalysis,
    analyze_goal_planning_snapshot,
)
from falcon_api.goal_planning.greedy import (
    GoalAllocationProjection,
    GoalMonthlyAllocation,
    MonthlyAllocationPeriod,
)
from falcon_api.goal_planning.guardrails import (
    OptimizationGuardrailAssessment,
    evaluate_optimization_guardrails,
)
from falcon_api.goal_planning.optimizer import (
    AllocationInvariantReport,
    ConstrainedOptimizationResult,
    ConstrainedOptimizationStatus,
    LinearProgramSolver,
    build_allocation_projections,
    calculate_weighted_funding_score,
    optimize_goal_allocations,
    verify_allocation_invariants,
)
from falcon_api.goal_planning.ranking import GoalRanking
from falcon_api.goal_planning.snapshot import GoalPlanningSnapshot
from falcon_api.models.enums import GoalType


GOAL_OPTIMIZATION_PLAN_POLICY_VERSION = "2026.1"


class GoalPlanStrategy(StrEnum):
    """Selected source of the contribution schedule."""

    OPTIMIZED = "optimized"
    GUARDED_GREEDY_FALLBACK = "guarded_greedy_fallback"
    BLOCKED = "blocked"


class GoalPlanReasonCode(StrEnum):
    """Stable explanations for selection or fallback."""

    OPTIMIZED_PLAN_SELECTED = "optimized_plan_selected"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    SOLVER_UNAVAILABLE_FALLBACK = "solver_unavailable_fallback"
    SOLVER_FAILURE_FALLBACK = "solver_failure_fallback"
    INVALID_SOLUTION_FALLBACK = "invalid_solution_fallback"
    NO_SOLUTION_FALLBACK = "no_solution_fallback"
    GUARDED_FALLBACK_OUTPERFORMED = "guarded_fallback_outperformed"
    EMERGENCY_RESERVE_APPLIED = "emergency_reserve_applied"


class GoalPlanAssumption(StrEnum):
    """Fixed Batch 4 assumptions that cannot be changed by a client."""

    PROTECTED_CAPACITY_ONLY = "protected_95_percent_capacity_only"
    LIQUID_BALANCE_EXCLUDED = "current_liquid_balance_excluded"
    SAVINGS_FORECAST_IS_POST_EXPENSE = "savings_forecast_is_post_expense"
    DEBT_PAYMENT_NOT_DOUBLE_COUNTED = "debt_payment_not_double_counted"
    DEADLINES_ARE_HARD_LIMITS = "deadlines_are_hard_limits"
    NO_CURRENCY_CONVERSION = "no_currency_conversion"
    PLAN_DOES_NOT_MOVE_MONEY = "plan_does_not_move_money"
    NO_SCENARIO_OVERRIDES = "no_scenario_overrides"


@dataclass(frozen=True, slots=True)
class GoalContributionSchedule:
    """One exact monthly schedule selected for display, not application."""

    strategy: GoalPlanStrategy
    allocation_band: str
    currency: str
    periods: tuple[MonthlyAllocationPeriod, ...]
    goal_projections: tuple[GoalAllocationProjection, ...]
    capacity_total: Decimal
    allocated_total: Decimal
    unallocated_total: Decimal
    weighted_funding_score: Decimal
    fully_funded_goal_count: int
    deadline_met_goal_count: int
    invariants: AllocationInvariantReport


@dataclass(frozen=True, slots=True)
class GoalPlanComparison:
    """Like-for-like greedy, guarded-fallback, optimizer, and selected metrics."""

    optimizer_status: ConstrainedOptimizationStatus | None
    greedy_baseline_guardrail_compliant: bool
    greedy_baseline_weighted_funding_score: Decimal
    greedy_baseline_allocated_total: Decimal
    greedy_baseline_fully_funded_goal_count: int
    greedy_baseline_deadline_met_goal_count: int
    guarded_fallback_weighted_funding_score: Decimal
    guarded_fallback_allocated_total: Decimal
    optimized_weighted_funding_score: Decimal | None
    optimized_allocated_total: Decimal | None
    optimized_fully_funded_goal_count: int | None
    optimized_deadline_met_goal_count: int | None
    optimized_score_delta_from_greedy: Decimal | None
    selected_weighted_funding_score: Decimal
    selected_allocated_total: Decimal
    selected_score_delta_from_greedy: Decimal


@dataclass(frozen=True, slots=True)
class GoalOptimizationPlan:
    """Auditable Batch 4 plan composed from one immutable evidence snapshot."""

    plan_id: str
    snapshot_id: str
    policy_version: str
    analysis: GoalPlanningAnalysis
    guardrails: OptimizationGuardrailAssessment
    optimizer_candidate: ConstrainedOptimizationResult | None
    schedule: GoalContributionSchedule
    comparison: GoalPlanComparison
    assumptions: tuple[GoalPlanAssumption, ...]
    reason_codes: tuple[GoalPlanReasonCode, ...]


def build_goal_optimization_plan(
    snapshot: GoalPlanningSnapshot,
    *,
    solver: LinearProgramSolver | None = None,
) -> GoalOptimizationPlan:
    """Build, verify, compare, and safely select one non-persistent schedule."""
    analysis = analyze_goal_planning_snapshot(snapshot)
    ranking = analysis.ranking
    guardrails = evaluate_optimization_guardrails(
        snapshot=snapshot,
        ranking=ranking,
    )
    reserve = guardrails.emergency_reserve_amount
    greedy_invariants = verify_allocation_invariants(
        snapshot=snapshot,
        ranking=ranking,
        periods=analysis.greedy_baseline.periods,
        emergency_reserve_amount=reserve,
    )
    greedy_score = calculate_weighted_funding_score(
        ranking=ranking,
        projections=analysis.greedy_baseline.goal_projections,
    )
    fallback_periods = _build_guarded_greedy_periods(
        snapshot=snapshot,
        ranking=ranking,
        emergency_reserve_amount=reserve,
    )
    fallback_schedule = _schedule(
        snapshot=snapshot,
        ranking=ranking,
        strategy=GoalPlanStrategy.GUARDED_GREEDY_FALLBACK,
        periods=fallback_periods,
        emergency_reserve_amount=reserve,
    )

    optimizer_candidate: ConstrainedOptimizationResult | None = None
    if not guardrails.can_optimize:
        selected = _schedule(
            snapshot=snapshot,
            ranking=ranking,
            strategy=GoalPlanStrategy.BLOCKED,
            periods=_zero_allocation_periods(snapshot),
            emergency_reserve_amount=reserve,
        )
        reasons = [GoalPlanReasonCode.GUARDRAIL_BLOCKED]
    else:
        optimizer_candidate = optimize_goal_allocations(
            snapshot=snapshot,
            ranking=ranking,
            emergency_reserve_amount=reserve,
            solver=solver,
        )
        if (
            optimizer_candidate.status is ConstrainedOptimizationStatus.OPTIMAL
            and optimizer_candidate.weighted_funding_score is not None
            and optimizer_candidate.weighted_funding_score
            >= fallback_schedule.weighted_funding_score
        ):
            selected = _schedule(
                snapshot=snapshot,
                ranking=ranking,
                strategy=GoalPlanStrategy.OPTIMIZED,
                periods=optimizer_candidate.periods,
                emergency_reserve_amount=reserve,
            )
            reasons = [GoalPlanReasonCode.OPTIMIZED_PLAN_SELECTED]
        else:
            selected = fallback_schedule
            reasons = [_fallback_reason(optimizer_candidate)]

    if reserve > 0:
        reasons.append(GoalPlanReasonCode.EMERGENCY_RESERVE_APPLIED)
    comparison = _comparison(
        analysis=analysis,
        greedy_score=greedy_score,
        greedy_invariants=greedy_invariants,
        fallback=fallback_schedule,
        optimizer=optimizer_candidate,
        selected=selected,
    )
    assumptions = tuple(GoalPlanAssumption)
    reason_codes = tuple(reasons)
    return GoalOptimizationPlan(
        plan_id=_plan_id(
            snapshot_id=snapshot.snapshot_id,
            strategy=selected.strategy,
            reserve=reserve,
            periods=selected.periods,
            reason_codes=reason_codes,
        ),
        snapshot_id=snapshot.snapshot_id,
        policy_version=GOAL_OPTIMIZATION_PLAN_POLICY_VERSION,
        analysis=analysis,
        guardrails=guardrails,
        optimizer_candidate=optimizer_candidate,
        schedule=selected,
        comparison=comparison,
        assumptions=assumptions,
        reason_codes=reason_codes,
    )


def _build_guarded_greedy_periods(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
    emergency_reserve_amount: Decimal,
) -> tuple[MonthlyAllocationPeriod, ...]:
    if snapshot.savings_capacity is None:
        return ()
    goals = {goal.goal_id: goal for goal in snapshot.goals}
    remaining = {
        goal_id: money(goal.remaining_amount) for goal_id, goal in goals.items()
    }
    cumulative_capacity = Decimal("0.0000")
    cumulative_non_emergency = Decimal("0.0000")
    periods: list[MonthlyAllocationPeriod] = []
    for point in sorted(
        snapshot.savings_capacity.points,
        key=lambda item: item.period_start,
    ):
        available = money(point.protected_amount)
        cumulative_capacity = money(cumulative_capacity + available)
        maximum_non_emergency = money(
            max(
                Decimal("0"),
                cumulative_capacity - emergency_reserve_amount,
            )
        )
        non_emergency_room = money(
            max(
                Decimal("0"),
                maximum_non_emergency - cumulative_non_emergency,
            )
        )
        allocations: list[GoalMonthlyAllocation] = []
        for ranked in ranking.items:
            goal = goals[ranked.goal_id]
            if (
                available == 0
                or not ranked.eligible_for_allocation
                or point.period_start > goal.target_date
                or remaining[goal.goal_id] == 0
            ):
                continue
            limit = available
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                limit = min(limit, non_emergency_room)
            amount = money(min(limit, remaining[goal.goal_id]))
            if amount == 0:
                continue
            remaining[goal.goal_id] = money(remaining[goal.goal_id] - amount)
            available = money(available - amount)
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                non_emergency_room = money(non_emergency_room - amount)
                cumulative_non_emergency = money(
                    cumulative_non_emergency + amount
                )
            allocations.append(
                GoalMonthlyAllocation(
                    goal_id=goal.goal_id,
                    rank=ranked.rank,
                    amount=amount,
                )
            )
        allocated = money(point.protected_amount - available)
        periods.append(
            MonthlyAllocationPeriod(
                period_start=point.period_start,
                available_capacity=money(point.protected_amount),
                allocated_amount=allocated,
                unallocated_amount=available,
                allocations=tuple(allocations),
            )
        )
    return tuple(periods)


def _zero_allocation_periods(
    snapshot: GoalPlanningSnapshot,
) -> tuple[MonthlyAllocationPeriod, ...]:
    if snapshot.savings_capacity is None:
        return ()
    return tuple(
        MonthlyAllocationPeriod(
            period_start=point.period_start,
            available_capacity=money(point.protected_amount),
            allocated_amount=Decimal("0.0000"),
            unallocated_amount=money(point.protected_amount),
            allocations=(),
        )
        for point in sorted(
            snapshot.savings_capacity.points,
            key=lambda item: item.period_start,
        )
    )


def _schedule(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
    strategy: GoalPlanStrategy,
    periods: tuple[MonthlyAllocationPeriod, ...],
    emergency_reserve_amount: Decimal,
) -> GoalContributionSchedule:
    projections = build_allocation_projections(
        snapshot=snapshot,
        ranking=ranking,
        periods=periods,
    )
    capacity_total = money(
        sum((period.available_capacity for period in periods), Decimal("0"))
    )
    allocated_total = money(
        sum((period.allocated_amount for period in periods), Decimal("0"))
    )
    funded_count, deadline_count = _goal_counts(projections)
    invariants = verify_allocation_invariants(
        snapshot=snapshot,
        ranking=ranking,
        periods=periods,
        emergency_reserve_amount=emergency_reserve_amount,
    )
    if not invariants.valid:
        raise ValueError("Selected goal schedule failed allocation invariants.")
    return GoalContributionSchedule(
        strategy=strategy,
        allocation_band="protected_95_percent_lower",
        currency=snapshot.currency,
        periods=periods,
        goal_projections=projections,
        capacity_total=capacity_total,
        allocated_total=allocated_total,
        unallocated_total=money(capacity_total - allocated_total),
        weighted_funding_score=calculate_weighted_funding_score(
            ranking=ranking,
            projections=projections,
        ),
        fully_funded_goal_count=funded_count,
        deadline_met_goal_count=deadline_count,
        invariants=invariants,
    )


def _goal_counts(
    projections: tuple[GoalAllocationProjection, ...],
) -> tuple[int, int]:
    eligible = tuple(
        item for item in projections if item.starting_remaining_amount > 0
    )
    return (
        sum(item.projected_remaining_amount == 0 for item in eligible),
        sum(item.deadline_met for item in eligible),
    )


def _comparison(
    *,
    analysis: GoalPlanningAnalysis,
    greedy_score: Decimal,
    greedy_invariants: AllocationInvariantReport,
    fallback: GoalContributionSchedule,
    optimizer: ConstrainedOptimizationResult | None,
    selected: GoalContributionSchedule,
) -> GoalPlanComparison:
    greedy_funded, greedy_deadline = _goal_counts(
        analysis.greedy_baseline.goal_projections
    )
    optimizer_funded: int | None = None
    optimizer_deadline: int | None = None
    optimized_score: Decimal | None = None
    optimized_allocated: Decimal | None = None
    if (
        optimizer is not None
        and optimizer.status is ConstrainedOptimizationStatus.OPTIMAL
    ):
        optimized_score = optimizer.weighted_funding_score
        optimized_allocated = optimizer.allocated_total
        optimizer_funded, optimizer_deadline = _goal_counts(
            optimizer.goal_projections
        )
    return GoalPlanComparison(
        optimizer_status=optimizer.status if optimizer is not None else None,
        greedy_baseline_guardrail_compliant=greedy_invariants.valid,
        greedy_baseline_weighted_funding_score=greedy_score,
        greedy_baseline_allocated_total=analysis.greedy_baseline.allocated_total,
        greedy_baseline_fully_funded_goal_count=greedy_funded,
        greedy_baseline_deadline_met_goal_count=greedy_deadline,
        guarded_fallback_weighted_funding_score=fallback.weighted_funding_score,
        guarded_fallback_allocated_total=fallback.allocated_total,
        optimized_weighted_funding_score=optimized_score,
        optimized_allocated_total=optimized_allocated,
        optimized_fully_funded_goal_count=optimizer_funded,
        optimized_deadline_met_goal_count=optimizer_deadline,
        optimized_score_delta_from_greedy=(
            (optimized_score - greedy_score).quantize(Decimal("0.0001"))
            if optimized_score is not None
            else None
        ),
        selected_weighted_funding_score=selected.weighted_funding_score,
        selected_allocated_total=selected.allocated_total,
        selected_score_delta_from_greedy=(
            selected.weighted_funding_score - greedy_score
        ).quantize(Decimal("0.0001")),
    )


def _fallback_reason(
    optimizer: ConstrainedOptimizationResult,
) -> GoalPlanReasonCode:
    if optimizer.status is ConstrainedOptimizationStatus.SOLVER_UNAVAILABLE:
        return GoalPlanReasonCode.SOLVER_UNAVAILABLE_FALLBACK
    if optimizer.status is ConstrainedOptimizationStatus.SOLVER_FAILED:
        return GoalPlanReasonCode.SOLVER_FAILURE_FALLBACK
    if optimizer.status is ConstrainedOptimizationStatus.INVALID_SOLUTION:
        return GoalPlanReasonCode.INVALID_SOLUTION_FALLBACK
    if optimizer.status is ConstrainedOptimizationStatus.NO_SOLUTION:
        return GoalPlanReasonCode.NO_SOLUTION_FALLBACK
    return GoalPlanReasonCode.GUARDED_FALLBACK_OUTPERFORMED


def _plan_id(
    *,
    snapshot_id: str,
    strategy: GoalPlanStrategy,
    reserve: Decimal,
    periods: tuple[MonthlyAllocationPeriod, ...],
    reason_codes: tuple[GoalPlanReasonCode, ...],
) -> str:
    payload = {
        "snapshot_id": snapshot_id,
        "policy_version": GOAL_OPTIMIZATION_PLAN_POLICY_VERSION,
        "strategy": strategy.value,
        "emergency_reserve": str(reserve),
        "reason_codes": [reason.value for reason in reason_codes],
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
