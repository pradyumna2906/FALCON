"""Constrained protected-capacity allocation with a pinned HiGHS adapter."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from falcon_api.analytics.types import MONEY_QUANTUM, money
from falcon_api.goal_planning.greedy import (
    GoalAllocationProjection,
    GoalMonthlyAllocation,
    MonthlyAllocationPeriod,
    validate_allocation_inputs,
)
from falcon_api.goal_planning.ranking import GoalRanking
from falcon_api.goal_planning.snapshot import GoalPlanningSnapshot
from falcon_api.models.enums import GoalType


CONSTRAINED_OPTIMIZATION_POLICY_VERSION = "2026.1"
WEIGHTED_SCORE_QUANTUM = Decimal("0.0001")
_NUMERICAL_TOLERANCE = 1e-7
_RANK_TIE_BREAK = Decimal("0.00000001")


class LinearSolverStatus(StrEnum):
    """Normalized outcomes from a replaceable linear-programming provider."""

    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ConstrainedOptimizationStatus(StrEnum):
    """Outcome of building and verifying one candidate allocation."""

    OPTIMAL = "optimal"
    NO_SOLUTION = "no_solution"
    SOLVER_UNAVAILABLE = "solver_unavailable"
    SOLVER_FAILED = "solver_failed"
    INVALID_SOLUTION = "invalid_solution"


class OptimizationReasonCode(StrEnum):
    """Stable reasons for a constrained-optimizer outcome."""

    HIGHS_OPTIMAL = "highs_optimal"
    NO_ELIGIBLE_GOALS = "no_eligible_goals"
    NO_PROTECTED_CAPACITY = "no_protected_capacity"
    NO_FEASIBLE_ALLOCATION_PERIODS = "no_feasible_allocation_periods"
    SOLVER_UNAVAILABLE = "solver_unavailable"
    SOLVER_INFEASIBLE = "solver_infeasible"
    SOLVER_UNBOUNDED = "solver_unbounded"
    SOLVER_FAILED = "solver_failed"
    SOLVER_OUTPUT_INVALID = "solver_output_invalid"
    ALLOCATION_INVARIANT_VIOLATION = "allocation_invariant_violation"


class AllocationInvariantViolation(StrEnum):
    """Machine-readable failure of an exact post-solver safety check."""

    CAPACITY_PERIOD_MISMATCH = "capacity_period_mismatch"
    PERIOD_TOTAL_MISMATCH = "period_total_mismatch"
    MONTHLY_CAPACITY_EXCEEDED = "monthly_capacity_exceeded"
    UNKNOWN_GOAL = "unknown_goal"
    RANK_MISMATCH = "rank_mismatch"
    DUPLICATE_GOAL_ALLOCATION = "duplicate_goal_allocation"
    NON_POSITIVE_ALLOCATION = "non_positive_allocation"
    GOAL_LIMIT_EXCEEDED = "goal_limit_exceeded"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    EMERGENCY_RESERVE_EXCEEDED = "emergency_reserve_exceeded"
    AGGREGATE_TOTAL_MISMATCH = "aggregate_total_mismatch"
    ALLOCATION_BOUND_VIOLATION = "allocation_bound_violation"


@dataclass(frozen=True, slots=True)
class LinearProgramSolution:
    """Provider-neutral linear-programming response."""

    status: LinearSolverStatus
    values: tuple[float, ...]
    objective_value: float | None
    solver_name: str
    solver_version: str | None
    message: str
    iterations: int | None


@dataclass(frozen=True, slots=True)
class GoalAllocationBound:
    """Optional exact per-goal monthly bound for downstream policy composition."""

    goal_id: UUID
    period_start: date
    minimum_amount: Decimal = Decimal("0")
    maximum_amount: Decimal | None = None


class LinearProgramSolver(Protocol):
    """Narrow adapter boundary that supports deterministic failure testing."""

    def solve(
        self,
        *,
        objective: tuple[float, ...],
        upper_bound_matrix: tuple[tuple[float, ...], ...],
        upper_bounds: tuple[float, ...],
        bounds: tuple[tuple[float, float | None], ...],
    ) -> LinearProgramSolution:
        """Minimize one bounded continuous linear program."""


class SciPyHighsSolver:
    """Lazy SciPy/HiGHS provider used by the production optimization extra."""

    def solve(
        self,
        *,
        objective: tuple[float, ...],
        upper_bound_matrix: tuple[tuple[float, ...], ...],
        upper_bounds: tuple[float, ...],
        bounds: tuple[tuple[float, float | None], ...],
    ) -> LinearProgramSolution:
        try:
            import scipy
            from scipy.optimize import linprog
        except ImportError:
            return LinearProgramSolution(
                status=LinearSolverStatus.UNAVAILABLE,
                values=(),
                objective_value=None,
                solver_name="scipy_highs",
                solver_version=None,
                message="SciPy/HiGHS is unavailable.",
                iterations=None,
            )

        try:
            result = linprog(
                objective,
                A_ub=upper_bound_matrix,
                b_ub=upper_bounds,
                bounds=bounds,
                method="highs",
                options={"presolve": True},
            )
        except Exception as error:  # pragma: no cover - provider safety boundary
            return LinearProgramSolution(
                status=LinearSolverStatus.FAILED,
                values=(),
                objective_value=None,
                solver_name="scipy_highs",
                solver_version=scipy.__version__,
                message=_bounded_message(str(error)),
                iterations=None,
            )

        status = {
            0: LinearSolverStatus.OPTIMAL,
            2: LinearSolverStatus.INFEASIBLE,
            3: LinearSolverStatus.UNBOUNDED,
        }.get(int(result.status), LinearSolverStatus.FAILED)
        raw_values = getattr(result, "x", None)
        values = (
            tuple(float(value) for value in raw_values)
            if raw_values is not None
            else ()
        )
        objective_value = getattr(result, "fun", None)
        iterations = getattr(result, "nit", None)
        return LinearProgramSolution(
            status=status,
            values=values,
            objective_value=(
                float(objective_value) if objective_value is not None else None
            ),
            solver_name="scipy_highs",
            solver_version=scipy.__version__,
            message=_bounded_message(str(result.message)),
            iterations=int(iterations) if iterations is not None else None,
        )


@dataclass(frozen=True, slots=True)
class AllocationInvariantReport:
    """Exact Decimal verification performed after every candidate solve."""

    evaluated: bool
    valid: bool
    checked_period_count: int
    checked_allocation_count: int
    violations: tuple[AllocationInvariantViolation, ...]


@dataclass(frozen=True, slots=True)
class ConstrainedOptimizationResult:
    """Immutable non-persistent optimizer candidate and solver evidence."""

    snapshot_id: str
    policy_version: str
    status: ConstrainedOptimizationStatus
    allocation_band: str
    currency: str
    emergency_reserve_amount: Decimal
    periods: tuple[MonthlyAllocationPeriod, ...]
    goal_projections: tuple[GoalAllocationProjection, ...]
    capacity_total: Decimal
    allocated_total: Decimal
    unallocated_total: Decimal
    weighted_funding_score: Decimal | None
    variable_count: int
    constraint_count: int
    solver: LinearProgramSolution | None
    invariants: AllocationInvariantReport
    reason_codes: tuple[OptimizationReasonCode, ...]


@dataclass(frozen=True, slots=True)
class _AllocationVariable:
    goal_id: UUID
    rank: int
    period_index: int


@dataclass(frozen=True, slots=True)
class _LinearProgramModel:
    allocation_variables: tuple[_AllocationVariable, ...]
    objective: tuple[float, ...]
    upper_bound_matrix: tuple[tuple[float, ...], ...]
    upper_bounds: tuple[float, ...]
    bounds: tuple[tuple[float, float | None], ...]


def optimize_goal_allocations(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
    emergency_reserve_amount: Decimal = Decimal("0"),
    allocation_bounds: tuple[GoalAllocationBound, ...] = (),
    solver: LinearProgramSolver | None = None,
) -> ConstrainedOptimizationResult:
    """Maximize ranking-weighted funded fractions under hard safety limits."""
    validate_allocation_inputs(snapshot=snapshot, ranking=ranking)
    reserve = _validated_reserve(emergency_reserve_amount)
    bounds = _validated_allocation_bounds(
        snapshot=snapshot,
        allocation_bounds=allocation_bounds,
    )
    eligible = tuple(item for item in ranking.items if item.eligible_for_allocation)
    if not eligible:
        return _empty_result(
            snapshot=snapshot,
            reserve=reserve,
            status=ConstrainedOptimizationStatus.NO_SOLUTION,
            reason=OptimizationReasonCode.NO_ELIGIBLE_GOALS,
        )
    capacity_total = money(
        snapshot.savings_capacity.protected_total
        if snapshot.savings_capacity is not None
        else Decimal("0")
    )
    if capacity_total <= 0:
        return _empty_result(
            snapshot=snapshot,
            reserve=reserve,
            status=ConstrainedOptimizationStatus.NO_SOLUTION,
            reason=OptimizationReasonCode.NO_PROTECTED_CAPACITY,
        )

    model = _build_model(
        snapshot=snapshot,
        ranking=ranking,
        reserve=reserve,
        allocation_bounds=bounds,
    )
    if not model.allocation_variables:
        return _empty_result(
            snapshot=snapshot,
            reserve=reserve,
            status=ConstrainedOptimizationStatus.NO_SOLUTION,
            reason=OptimizationReasonCode.NO_FEASIBLE_ALLOCATION_PERIODS,
        )
    provider = solver or SciPyHighsSolver()
    solution = provider.solve(
        objective=model.objective,
        upper_bound_matrix=model.upper_bound_matrix,
        upper_bounds=model.upper_bounds,
        bounds=model.bounds,
    )
    if solution.status is not LinearSolverStatus.OPTIMAL:
        reason = {
            LinearSolverStatus.UNAVAILABLE: OptimizationReasonCode.SOLVER_UNAVAILABLE,
            LinearSolverStatus.INFEASIBLE: OptimizationReasonCode.SOLVER_INFEASIBLE,
            LinearSolverStatus.UNBOUNDED: OptimizationReasonCode.SOLVER_UNBOUNDED,
            LinearSolverStatus.FAILED: OptimizationReasonCode.SOLVER_FAILED,
        }[solution.status]
        status = (
            ConstrainedOptimizationStatus.SOLVER_UNAVAILABLE
            if solution.status is LinearSolverStatus.UNAVAILABLE
            else ConstrainedOptimizationStatus.SOLVER_FAILED
        )
        return _empty_result(
            snapshot=snapshot,
            reserve=reserve,
            status=status,
            reason=reason,
            model=model,
            solver=solution,
        )
    if not _solution_is_valid(model=model, solution=solution):
        return _empty_result(
            snapshot=snapshot,
            reserve=reserve,
            status=ConstrainedOptimizationStatus.INVALID_SOLUTION,
            reason=OptimizationReasonCode.SOLVER_OUTPUT_INVALID,
            model=model,
            solver=solution,
        )

    periods = _periods_from_solution(
        snapshot=snapshot,
        variables=model.allocation_variables,
        values=solution.values,
    )
    projections = build_allocation_projections(
        snapshot=snapshot,
        ranking=ranking,
        periods=periods,
    )
    invariants = verify_allocation_invariants(
        snapshot=snapshot,
        ranking=ranking,
        periods=periods,
        emergency_reserve_amount=reserve,
        allocation_bounds=allocation_bounds,
    )
    if not invariants.valid:
        return _empty_result(
            snapshot=snapshot,
            reserve=reserve,
            status=ConstrainedOptimizationStatus.INVALID_SOLUTION,
            reason=OptimizationReasonCode.ALLOCATION_INVARIANT_VIOLATION,
            model=model,
            solver=solution,
            invariants=invariants,
        )

    allocated_total = money(
        sum((period.allocated_amount for period in periods), Decimal("0"))
    )
    return ConstrainedOptimizationResult(
        snapshot_id=snapshot.snapshot_id,
        policy_version=CONSTRAINED_OPTIMIZATION_POLICY_VERSION,
        status=ConstrainedOptimizationStatus.OPTIMAL,
        allocation_band="protected_95_percent_lower",
        currency=snapshot.currency,
        emergency_reserve_amount=reserve,
        periods=periods,
        goal_projections=projections,
        capacity_total=capacity_total,
        allocated_total=allocated_total,
        unallocated_total=money(capacity_total - allocated_total),
        weighted_funding_score=calculate_weighted_funding_score(
            ranking=ranking,
            projections=projections,
        ),
        variable_count=len(model.objective),
        constraint_count=len(model.upper_bounds),
        solver=solution,
        invariants=invariants,
        reason_codes=(OptimizationReasonCode.HIGHS_OPTIMAL,),
    )


def build_allocation_projections(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
    periods: tuple[MonthlyAllocationPeriod, ...],
) -> tuple[GoalAllocationProjection, ...]:
    """Create exact per-goal outcomes from any verified monthly schedule."""
    goals = {goal.goal_id: goal for goal in snapshot.goals}
    allocated = {goal_id: Decimal("0.0000") for goal_id in goals}
    completion: dict[UUID, date | None] = {
        goal_id: (snapshot.local_date if goal.remaining_amount == 0 else None)
        for goal_id, goal in goals.items()
    }
    for period in sorted(periods, key=lambda item: item.period_start):
        for allocation in period.allocations:
            if allocation.goal_id not in goals:
                continue
            allocated[allocation.goal_id] = money(
                allocated[allocation.goal_id] + allocation.amount
            )
            goal = goals[allocation.goal_id]
            if (
                completion[allocation.goal_id] is None
                and allocated[allocation.goal_id] >= goal.remaining_amount
            ):
                completion[allocation.goal_id] = period.period_start

    return tuple(
        GoalAllocationProjection(
            goal_id=item.goal_id,
            rank=item.rank,
            starting_remaining_amount=money(goals[item.goal_id].remaining_amount),
            allocated_amount=money(allocated[item.goal_id]),
            projected_remaining_amount=money(
                max(
                    Decimal("0"),
                    goals[item.goal_id].remaining_amount - allocated[item.goal_id],
                )
            ),
            projected_completion_period=completion[item.goal_id],
            deadline_met=(
                completion[item.goal_id] is not None
                and completion[item.goal_id] <= goals[item.goal_id].target_date
            ),
        )
        for item in ranking.items
    )


def calculate_weighted_funding_score(
    *,
    ranking: GoalRanking,
    projections: tuple[GoalAllocationProjection, ...],
) -> Decimal:
    """Return the ranking-weighted funded percentage for eligible goals."""
    projection_by_id = {item.goal_id: item for item in projections}
    numerator = Decimal("0")
    denominator = Decimal("0")
    for item in ranking.items:
        projection = projection_by_id.get(item.goal_id)
        if (
            projection is None
            or not item.eligible_for_allocation
            or projection.starting_remaining_amount <= 0
        ):
            continue
        funded_fraction = min(
            Decimal("1"),
            projection.allocated_amount / projection.starting_remaining_amount,
        )
        numerator += item.score.total * funded_fraction
        denominator += item.score.total
    if denominator == 0:
        return Decimal("0.0000")
    return ((numerator / denominator) * Decimal("100")).quantize(
        WEIGHTED_SCORE_QUANTUM
    )


def verify_allocation_invariants(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
    periods: tuple[MonthlyAllocationPeriod, ...],
    emergency_reserve_amount: Decimal = Decimal("0"),
    allocation_bounds: tuple[GoalAllocationBound, ...] = (),
) -> AllocationInvariantReport:
    """Verify capacity, goal, deadline, rank, and emergency-reserve limits."""
    reserve = _validated_reserve(emergency_reserve_amount)
    bounds = _validated_allocation_bounds(
        snapshot=snapshot,
        allocation_bounds=allocation_bounds,
    )
    violations: list[AllocationInvariantViolation] = []
    expected_points = (
        tuple(
            sorted(
                snapshot.savings_capacity.points,
                key=lambda item: item.period_start,
            )
        )
        if snapshot.savings_capacity is not None
        else ()
    )
    if tuple(period.period_start for period in periods) != tuple(
        point.period_start for point in expected_points
    ):
        _add_violation(
            violations,
            AllocationInvariantViolation.CAPACITY_PERIOD_MISMATCH,
        )

    goals = {goal.goal_id: goal for goal in snapshot.goals}
    ranks = {item.goal_id: item.rank for item in ranking.items}
    goal_totals = {goal_id: Decimal("0.0000") for goal_id in goals}
    cumulative_capacity = Decimal("0.0000")
    cumulative_non_emergency = Decimal("0.0000")
    allocation_count = 0
    allocation_by_goal_period: dict[tuple[UUID, date], Decimal] = {}
    for index, period in enumerate(periods):
        expected_capacity = (
            money(expected_points[index].protected_amount)
            if index < len(expected_points)
            and expected_points[index].period_start == period.period_start
            else None
        )
        if expected_capacity is None or period.available_capacity != expected_capacity:
            _add_violation(
                violations,
                AllocationInvariantViolation.CAPACITY_PERIOD_MISMATCH,
            )
        allocation_sum = money(
            sum((item.amount for item in period.allocations), Decimal("0"))
        )
        if (
            period.allocated_amount != allocation_sum
            or period.unallocated_amount
            != money(period.available_capacity - period.allocated_amount)
        ):
            _add_violation(
                violations,
                AllocationInvariantViolation.PERIOD_TOTAL_MISMATCH,
            )
        if (
            period.allocated_amount < 0
            or period.allocated_amount > period.available_capacity
        ):
            _add_violation(
                violations,
                AllocationInvariantViolation.MONTHLY_CAPACITY_EXCEEDED,
            )

        seen_goal_ids: set[UUID] = set()
        for allocation in period.allocations:
            allocation_count += 1
            if allocation.goal_id in seen_goal_ids:
                _add_violation(
                    violations,
                    AllocationInvariantViolation.DUPLICATE_GOAL_ALLOCATION,
                )
            seen_goal_ids.add(allocation.goal_id)
            goal = goals.get(allocation.goal_id)
            if goal is None:
                _add_violation(
                    violations,
                    AllocationInvariantViolation.UNKNOWN_GOAL,
                )
                continue
            if allocation.rank != ranks.get(allocation.goal_id):
                _add_violation(
                    violations,
                    AllocationInvariantViolation.RANK_MISMATCH,
                )
            if allocation.amount <= 0:
                _add_violation(
                    violations,
                    AllocationInvariantViolation.NON_POSITIVE_ALLOCATION,
                )
            if period.period_start > goal.target_date:
                _add_violation(
                    violations,
                    AllocationInvariantViolation.DEADLINE_EXCEEDED,
                )
            goal_totals[allocation.goal_id] = money(
                goal_totals[allocation.goal_id] + allocation.amount
            )
            key = (allocation.goal_id, period.period_start)
            allocation_by_goal_period[key] = money(
                allocation_by_goal_period.get(key, Decimal("0"))
                + allocation.amount
            )
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                cumulative_non_emergency = money(
                    cumulative_non_emergency + allocation.amount
                )
        cumulative_capacity = money(
            cumulative_capacity + period.available_capacity
        )
        maximum_non_emergency = money(
            max(Decimal("0"), cumulative_capacity - reserve)
        )
        if cumulative_non_emergency > maximum_non_emergency:
            _add_violation(
                violations,
                AllocationInvariantViolation.EMERGENCY_RESERVE_EXCEEDED,
            )

    for goal_id, total in goal_totals.items():
        if total > money(goals[goal_id].remaining_amount):
            _add_violation(
                violations,
                AllocationInvariantViolation.GOAL_LIMIT_EXCEEDED,
            )
    for key, bound in bounds.items():
        actual = allocation_by_goal_period.get(key, Decimal("0.0000"))
        if actual < bound.minimum_amount or (
            bound.maximum_amount is not None
            and actual > bound.maximum_amount
        ):
            _add_violation(
                violations,
                AllocationInvariantViolation.ALLOCATION_BOUND_VIOLATION,
            )
    capacity_total = money(
        sum((period.available_capacity for period in periods), Decimal("0"))
    )
    allocated_total = money(
        sum((period.allocated_amount for period in periods), Decimal("0"))
    )
    unallocated_total = money(
        sum((period.unallocated_amount for period in periods), Decimal("0"))
    )
    if capacity_total != money(allocated_total + unallocated_total):
        _add_violation(
            violations,
            AllocationInvariantViolation.AGGREGATE_TOTAL_MISMATCH,
        )
    return AllocationInvariantReport(
        evaluated=True,
        valid=not violations,
        checked_period_count=len(periods),
        checked_allocation_count=allocation_count,
        violations=tuple(violations),
    )


def _build_model(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
    reserve: Decimal,
    allocation_bounds: dict[tuple[UUID, date], GoalAllocationBound],
) -> _LinearProgramModel:
    assert snapshot.savings_capacity is not None
    points = tuple(
        sorted(snapshot.savings_capacity.points, key=lambda item: item.period_start)
    )
    goals = {goal.goal_id: goal for goal in snapshot.goals}
    allocation_variables = tuple(
        _AllocationVariable(
            goal_id=item.goal_id,
            rank=item.rank,
            period_index=period_index,
        )
        for period_index, point in enumerate(points)
        for item in ranking.items
        if item.eligible_for_allocation
        and point.period_start <= goals[item.goal_id].target_date
    )
    eligible_items = tuple(
        item
        for item in ranking.items
        if any(variable.goal_id == item.goal_id for variable in allocation_variables)
    )
    allocation_count = len(allocation_variables)
    variable_count = allocation_count + len(eligible_items)
    objective = [0.0] * variable_count
    fraction_index: dict[UUID, int] = {}
    for offset, item in enumerate(eligible_items):
        index = allocation_count + offset
        fraction_index[item.goal_id] = index
        tie_break = _RANK_TIE_BREAK * Decimal(
            len(ranking.items) - item.rank + 1
        )
        objective[index] = -float(item.score.total + tie_break)

    rows: list[tuple[float, ...]] = []
    limits: list[float] = []
    for period_index, point in enumerate(points):
        row = [0.0] * variable_count
        for index, variable in enumerate(allocation_variables):
            if variable.period_index == period_index:
                row[index] = 1.0
        rows.append(tuple(row))
        limits.append(float(point.protected_amount))

    for item in eligible_items:
        goal = goals[item.goal_id]
        cap_row = [0.0] * variable_count
        fraction_row = [0.0] * variable_count
        for index, variable in enumerate(allocation_variables):
            if variable.goal_id == item.goal_id:
                cap_row[index] = 1.0
                fraction_row[index] = -1.0
        fraction_row[fraction_index[item.goal_id]] = float(goal.remaining_amount)
        rows.extend((tuple(cap_row), tuple(fraction_row)))
        limits.extend((float(goal.remaining_amount), 0.0))

    if reserve > 0:
        cumulative_capacity = Decimal("0")
        for period_index, point in enumerate(points):
            cumulative_capacity += point.protected_amount
            row = [0.0] * variable_count
            for index, variable in enumerate(allocation_variables):
                goal = goals[variable.goal_id]
                if (
                    variable.period_index <= period_index
                    and goal.goal_type is not GoalType.EMERGENCY_FUND
                ):
                    row[index] = 1.0
            rows.append(tuple(row))
            limits.append(
                float(max(Decimal("0"), cumulative_capacity - reserve))
            )

    bounds = tuple(
        _provider_bound(
            variable=variable,
            period_start=points[variable.period_index].period_start,
            remaining=goals[variable.goal_id].remaining_amount,
            allocation_bounds=allocation_bounds,
        )
        for variable in allocation_variables
    ) + tuple((0.0, 1.0) for _ in eligible_items)
    return _LinearProgramModel(
        allocation_variables=allocation_variables,
        objective=tuple(objective),
        upper_bound_matrix=tuple(rows),
        upper_bounds=tuple(limits),
        bounds=bounds,
    )


def _solution_is_valid(
    *,
    model: _LinearProgramModel,
    solution: LinearProgramSolution,
) -> bool:
    values = solution.values
    if (
        solution.objective_value is not None
        and not math.isfinite(solution.objective_value)
    ):
        return False
    if len(values) != len(model.objective):
        return False
    if any(not math.isfinite(value) for value in values):
        return False
    for value, (lower, upper) in zip(values, model.bounds, strict=True):
        if value < lower - _NUMERICAL_TOLERANCE:
            return False
        if upper is not None and value > upper + _scaled_tolerance(upper):
            return False
    for row, limit in zip(
        model.upper_bound_matrix,
        model.upper_bounds,
        strict=True,
    ):
        actual = sum(
            coefficient * value
            for coefficient, value in zip(row, values, strict=True)
        )
        if actual > limit + _scaled_tolerance(limit):
            return False
    return True


def _periods_from_solution(
    *,
    snapshot: GoalPlanningSnapshot,
    variables: tuple[_AllocationVariable, ...],
    values: tuple[float, ...],
) -> tuple[MonthlyAllocationPeriod, ...]:
    assert snapshot.savings_capacity is not None
    points = tuple(
        sorted(snapshot.savings_capacity.points, key=lambda item: item.period_start)
    )
    by_period: list[list[GoalMonthlyAllocation]] = [[] for _ in points]
    for variable, raw_value in zip(variables, values, strict=False):
        normalized = Decimal(str(max(0.0, raw_value))).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_DOWN,
        )
        if normalized > 0:
            by_period[variable.period_index].append(
                GoalMonthlyAllocation(
                    goal_id=variable.goal_id,
                    rank=variable.rank,
                    amount=normalized,
                )
            )
    periods: list[MonthlyAllocationPeriod] = []
    for index, point in enumerate(points):
        allocations = tuple(sorted(by_period[index], key=lambda item: item.rank))
        available = money(point.protected_amount)
        allocated = money(
            sum((item.amount for item in allocations), Decimal("0"))
        )
        periods.append(
            MonthlyAllocationPeriod(
                period_start=point.period_start,
                available_capacity=available,
                allocated_amount=allocated,
                unallocated_amount=money(available - allocated),
                allocations=allocations,
            )
        )
    return tuple(periods)


def _empty_result(
    *,
    snapshot: GoalPlanningSnapshot,
    reserve: Decimal,
    status: ConstrainedOptimizationStatus,
    reason: OptimizationReasonCode,
    model: _LinearProgramModel | None = None,
    solver: LinearProgramSolution | None = None,
    invariants: AllocationInvariantReport | None = None,
) -> ConstrainedOptimizationResult:
    capacity_total = money(
        snapshot.savings_capacity.protected_total
        if snapshot.savings_capacity is not None
        else Decimal("0")
    )
    return ConstrainedOptimizationResult(
        snapshot_id=snapshot.snapshot_id,
        policy_version=CONSTRAINED_OPTIMIZATION_POLICY_VERSION,
        status=status,
        allocation_band="protected_95_percent_lower",
        currency=snapshot.currency,
        emergency_reserve_amount=reserve,
        periods=(),
        goal_projections=(),
        capacity_total=capacity_total,
        allocated_total=Decimal("0.0000"),
        unallocated_total=capacity_total,
        weighted_funding_score=None,
        variable_count=len(model.objective) if model is not None else 0,
        constraint_count=len(model.upper_bounds) if model is not None else 0,
        solver=solver,
        invariants=invariants or _not_evaluated_invariants(),
        reason_codes=(reason,),
    )


def _not_evaluated_invariants() -> AllocationInvariantReport:
    return AllocationInvariantReport(
        evaluated=False,
        valid=False,
        checked_period_count=0,
        checked_allocation_count=0,
        violations=(),
    )


def _validated_reserve(value: Decimal) -> Decimal:
    resolved = Decimal(value)
    if not resolved.is_finite() or resolved < 0:
        raise ValueError("Emergency reserve must be finite and non-negative.")
    return money(resolved)


def _validated_allocation_bounds(
    *,
    snapshot: GoalPlanningSnapshot,
    allocation_bounds: tuple[GoalAllocationBound, ...],
) -> dict[tuple[UUID, date], GoalAllocationBound]:
    goal_ids = {goal.goal_id for goal in snapshot.goals}
    periods = {
        point.period_start
        for point in (
            snapshot.savings_capacity.points
            if snapshot.savings_capacity is not None
            else ()
        )
    }
    result: dict[tuple[UUID, date], GoalAllocationBound] = {}
    for bound in allocation_bounds:
        minimum = Decimal(bound.minimum_amount)
        maximum = (
            Decimal(bound.maximum_amount)
            if bound.maximum_amount is not None
            else None
        )
        if bound.goal_id not in goal_ids or bound.period_start not in periods:
            raise ValueError(
                "Allocation bounds must reference scenario goals and periods."
            )
        if (
            not minimum.is_finite()
            or minimum < 0
            or (maximum is not None and (not maximum.is_finite() or maximum < minimum))
        ):
            raise ValueError(
                "Allocation bounds must be finite, non-negative, and ordered."
            )
        key = (bound.goal_id, bound.period_start)
        if key in result:
            raise ValueError(
                "Allocation bounds must be unique by goal and period."
            )
        result[key] = GoalAllocationBound(
            goal_id=bound.goal_id,
            period_start=bound.period_start,
            minimum_amount=money(minimum),
            maximum_amount=money(maximum) if maximum is not None else None,
        )
    return result


def _provider_bound(
    *,
    variable: _AllocationVariable,
    period_start: date,
    remaining: Decimal,
    allocation_bounds: dict[tuple[UUID, date], GoalAllocationBound],
) -> tuple[float, float | None]:
    bound = allocation_bounds.get((variable.goal_id, period_start))
    if bound is None:
        return 0.0, float(remaining)
    upper = min(
        remaining,
        bound.maximum_amount if bound.maximum_amount is not None else remaining,
    )
    return float(bound.minimum_amount), float(upper)


def _scaled_tolerance(value: float) -> float:
    return _NUMERICAL_TOLERANCE * max(1.0, abs(value))


def _add_violation(
    violations: list[AllocationInvariantViolation],
    violation: AllocationInvariantViolation,
) -> None:
    if violation not in violations:
        violations.append(violation)


def _bounded_message(value: str) -> str:
    return " ".join(value.split())[:240]
