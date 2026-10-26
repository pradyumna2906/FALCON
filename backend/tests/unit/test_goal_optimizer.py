"""Checkpoints 10.9–10.10 constrained optimizer and invariant tests."""

import builtins
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from falcon_api.goal_planning import (
    CONSTRAINED_OPTIMIZATION_POLICY_VERSION,
    AllocationInvariantViolation,
    ConstrainedOptimizationStatus,
    GoalMonthlyAllocation,
    LinearProgramSolution,
    LinearSolverStatus,
    MonthlyAllocationPeriod,
    OptimizationReasonCode,
    SavingsCapacityPlan,
    SavingsCapacityPoint,
    SciPyHighsSolver,
    analyze_goal_planning_snapshot,
    calculate_goal_progress,
    calculate_weighted_funding_score,
    optimize_goal_allocations,
    verify_allocation_invariants,
)
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningBudgetEvidence,
    PlanningFinancialEvidence,
    PlanningProvenance,
)
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class _StatusSolver:
    def __init__(
        self,
        status: LinearSolverStatus,
        *,
        invalid_values: bool = False,
    ) -> None:
        self.status = status
        self.invalid_values = invalid_values

    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del upper_bound_matrix, upper_bounds, bounds
        if self.invalid_values:
            values = tuple(float("nan") for _ in objective)
        else:
            values = ()
        return LinearProgramSolution(
            status=self.status,
            values=values,
            objective_value=None,
            solver_name="test_solver",
            solver_version="1",
            message="test outcome",
            iterations=0,
        )


class _OverspendingSolver:
    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del upper_bound_matrix, upper_bounds, bounds
        return LinearProgramSolution(
            status=LinearSolverStatus.OPTIMAL,
            values=tuple(1_000_000.0 for _ in objective),
            objective_value=-1.0,
            solver_name="unsafe_test_solver",
            solver_version="1",
            message="claims success",
            iterations=1,
        )


class _ToleranceSlipSolver:
    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del upper_bound_matrix, upper_bounds, bounds
        values = [0.0 for _ in objective]
        values[0] = 1_000_000_000.01
        values[-1] = 0.5
        return LinearProgramSolution(
            status=LinearSolverStatus.OPTIMAL,
            values=tuple(values),
            objective_value=-1.0,
            solver_name="tolerance_test_solver",
            solver_version="1",
            message="within floating tolerance",
            iterations=1,
        )


def _goal(
    *,
    goal_id: UUID | None = None,
    name: str,
    target: str,
    priority: GoalPriority,
    goal_type: GoalType = GoalType.OTHER,
    deadline: date = date(2026, 12, 31),
):
    model = Goal(
        id=goal_id or uuid4(),
        user_id=uuid4(),
        name=name,
        goal_type=goal_type,
        target_amount=Decimal(target),
        starting_amount=Decimal("0"),
        currency="INR",
        target_date=deadline,
        priority=priority,
        status=GoalStatus.ACTIVE,
        description=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return calculate_goal_progress(
        goal=model,
        contribution_amount=Decimal("0"),
        calculated_on=date(2026, 9, 15),
    )


def _snapshot(
    goals,
    *,
    amounts: tuple[str, ...] = ("50", "50"),
    periods: tuple[date, ...] | None = None,
) -> GoalPlanningSnapshot:
    resolved_periods = periods or tuple(
        date(2026, month, 1) for month in range(10, 10 + len(amounts))
    )
    points = tuple(
        SavingsCapacityPoint(
            period_start=period,
            protected_amount=Decimal(amount),
            expected_amount=Decimal(amount),
            upside_amount=Decimal(amount),
        )
        for period, amount in zip(resolved_periods, amounts, strict=True)
    )
    capacity = SavingsCapacityPlan(
        forecast_run_id=uuid4(),
        currency="INR",
        policy_version="2026.1",
        protection_band="95_percent",
        reliability="normal",
        points=points,
        protected_total=sum(
            (point.protected_amount for point in points), Decimal("0")
        ),
        expected_total=sum(
            (point.expected_amount for point in points), Decimal("0")
        ),
        upside_total=sum((point.upside_amount for point in points), Decimal("0")),
    )
    return GoalPlanningSnapshot(
        snapshot_id="a" * 64,
        contract_version="2026.1",
        cutoff_at=_NOW,
        local_date=date(2026, 9, 15),
        timezone="Asia/Kolkata",
        currency="INR",
        goals=tuple(goals),
        profile=None,
        finances=PlanningFinancialEvidence(
            liquid_balance=Decimal("0"),
            liability_account_count=0,
            liability_payment_count=0,
            outstanding_debt=Decimal("0"),
            monthly_debt_payment=Decimal("0"),
            source_last_updated_at=None,
        ),
        budgets=PlanningBudgetEvidence(
            active_budget_count=0,
            budget_with_overall_limit_count=0,
            total_overall_limit=Decimal("0"),
            source_last_updated_at=None,
        ),
        savings_capacity=capacity,
        warnings=(),
        provenance=PlanningProvenance(
            goal_ids=tuple(goal.goal_id for goal in goals),
            contribution_count=0,
            forecast_run_id=capacity.forecast_run_id,
            source_last_updated_at=_NOW,
        ),
    )


def _optimize(snapshot: GoalPlanningSnapshot, **changes):
    return optimize_goal_allocations(
        snapshot=snapshot,
        ranking=analyze_goal_planning_snapshot(snapshot).ranking,
        **changes,
    )


def test_highs_optimizes_ranking_weighted_fraction_and_beats_greedy() -> None:
    large_high_rank = _goal(
        goal_id=UUID(int=1),
        name="Large critical goal",
        target="1000",
        priority=GoalPriority.CRITICAL,
    )
    small_low_rank = _goal(
        goal_id=UUID(int=2),
        name="Small goal",
        target="100",
        priority=GoalPriority.LOW,
    )
    snapshot = _snapshot((large_high_rank, small_low_rank))
    analysis = analyze_goal_planning_snapshot(snapshot)

    result = optimize_goal_allocations(
        snapshot=snapshot,
        ranking=analysis.ranking,
    )

    assert result.policy_version == CONSTRAINED_OPTIMIZATION_POLICY_VERSION == "2026.1"
    assert result.status is ConstrainedOptimizationStatus.OPTIMAL
    assert result.solver is not None
    assert result.solver.status is LinearSolverStatus.OPTIMAL
    assert result.solver.solver_name == "scipy_highs"
    assert result.variable_count > 0
    assert result.constraint_count > 0
    assert result.invariants.valid is True
    assert result.allocated_total == Decimal("100.0000")
    small_projection = next(
        item
        for item in result.goal_projections
        if item.goal_id == small_low_rank.goal_id
    )
    assert small_projection.projected_remaining_amount == Decimal("0.0000")
    greedy_score = calculate_weighted_funding_score(
        ranking=analysis.ranking,
        projections=analysis.greedy_baseline.goal_projections,
    )
    assert result.weighted_funding_score is not None
    assert result.weighted_funding_score > greedy_score


def test_optimizer_enforces_deadlines_and_four_decimal_exactness() -> None:
    urgent = _goal(
        name="October",
        target="100.1234",
        priority=GoalPriority.HIGH,
        deadline=date(2026, 10, 15),
    )
    later = _goal(
        name="December",
        target="200",
        priority=GoalPriority.MEDIUM,
    )
    snapshot = _snapshot(
        (urgent, later),
        amounts=("75.1234", "100.0000"),
    )

    result = _optimize(snapshot)

    assert result.status is ConstrainedOptimizationStatus.OPTIMAL
    assert all(
        allocation.goal_id != urgent.goal_id
        for allocation in result.periods[1].allocations
    )
    assert all(
        allocation.amount.as_tuple().exponent == -4
        for period in result.periods
        for allocation in period.allocations
    )
    assert result.allocated_total <= result.capacity_total
    assert result.invariants.violations == ()


def test_emergency_reserve_caps_non_emergency_allocations_by_prefix() -> None:
    emergency = _goal(
        name="Emergency reserve",
        target="600",
        priority=GoalPriority.CRITICAL,
        goal_type=GoalType.EMERGENCY_FUND,
    )
    travel = _goal(
        name="Travel",
        target="1000",
        priority=GoalPriority.HIGH,
        goal_type=GoalType.TRAVEL,
    )
    snapshot = _snapshot((travel, emergency), amounts=("500", "500"))

    result = _optimize(snapshot, emergency_reserve_amount=Decimal("600"))

    assert result.status is ConstrainedOptimizationStatus.OPTIMAL
    travel_total = sum(
        (
            allocation.amount
            for period in result.periods
            for allocation in period.allocations
            if allocation.goal_id == travel.goal_id
        ),
        Decimal("0"),
    )
    assert travel_total <= Decimal("400.0000")
    assert all(
        allocation.goal_id != travel.goal_id
        for allocation in result.periods[0].allocations
    )
    assert result.invariants.valid is True


def test_reserve_remains_unallocated_when_no_emergency_goal_exists() -> None:
    travel = _goal(
        name="Travel",
        target="1000",
        priority=GoalPriority.CRITICAL,
        goal_type=GoalType.TRAVEL,
    )
    snapshot = _snapshot((travel,), amounts=("500", "500"))

    result = _optimize(snapshot, emergency_reserve_amount=Decimal("600"))

    assert result.status is ConstrainedOptimizationStatus.OPTIMAL
    assert result.allocated_total <= Decimal("400.0000")
    assert result.unallocated_total >= Decimal("600.0000")


@pytest.mark.parametrize(
    ("solver_status", "expected_status", "expected_reason"),
    [
        (
            LinearSolverStatus.UNAVAILABLE,
            ConstrainedOptimizationStatus.SOLVER_UNAVAILABLE,
            OptimizationReasonCode.SOLVER_UNAVAILABLE,
        ),
        (
            LinearSolverStatus.INFEASIBLE,
            ConstrainedOptimizationStatus.SOLVER_FAILED,
            OptimizationReasonCode.SOLVER_INFEASIBLE,
        ),
        (
            LinearSolverStatus.UNBOUNDED,
            ConstrainedOptimizationStatus.SOLVER_FAILED,
            OptimizationReasonCode.SOLVER_UNBOUNDED,
        ),
        (
            LinearSolverStatus.FAILED,
            ConstrainedOptimizationStatus.SOLVER_FAILED,
            OptimizationReasonCode.SOLVER_FAILED,
        ),
    ],
)
def test_solver_failures_are_normalized_without_allocating_money(
    solver_status,
    expected_status,
    expected_reason,
) -> None:
    snapshot = _snapshot(
        (_goal(name="Goal", target="100", priority=GoalPriority.HIGH),)
    )

    result = _optimize(snapshot, solver=_StatusSolver(solver_status))

    assert result.status is expected_status
    assert result.reason_codes == (expected_reason,)
    assert result.periods == ()
    assert result.allocated_total == Decimal("0.0000")
    assert result.invariants.evaluated is False


@pytest.mark.parametrize(
    "solver",
    [
        _StatusSolver(LinearSolverStatus.OPTIMAL, invalid_values=True),
        _OverspendingSolver(),
    ],
)
def test_malformed_or_constraint_violating_solver_output_is_rejected(solver) -> None:
    snapshot = _snapshot(
        (_goal(name="Goal", target="100", priority=GoalPriority.HIGH),)
    )

    result = _optimize(snapshot, solver=solver)

    assert result.status is ConstrainedOptimizationStatus.INVALID_SOLUTION
    assert result.reason_codes == (OptimizationReasonCode.SOLVER_OUTPUT_INVALID,)
    assert result.periods == ()


def test_exact_invariants_reject_a_candidate_inside_scaled_float_tolerance() -> None:
    goal = _goal(
        name="Large goal",
        target="2000000000",
        priority=GoalPriority.HIGH,
    )
    snapshot = _snapshot((goal,), amounts=("1000000000",))

    result = _optimize(snapshot, solver=_ToleranceSlipSolver())

    assert result.status is ConstrainedOptimizationStatus.INVALID_SOLUTION
    assert result.reason_codes == (
        OptimizationReasonCode.ALLOCATION_INVARIANT_VIOLATION,
    )
    assert result.invariants.evaluated is True
    assert AllocationInvariantViolation.MONTHLY_CAPACITY_EXCEEDED in (
        result.invariants.violations
    )


def test_optimizer_returns_explicit_no_solution_outcomes() -> None:
    goal = _goal(
        name="Expired before forecast",
        target="100",
        priority=GoalPriority.HIGH,
        deadline=date(2026, 9, 30),
    )
    no_periods = _snapshot((goal,))
    no_goals = replace(
        no_periods,
        goals=(),
        provenance=replace(no_periods.provenance, goal_ids=()),
    )
    no_capacity = replace(
        no_periods,
        savings_capacity=replace(
            no_periods.savings_capacity,
            points=tuple(
                replace(point, protected_amount=Decimal("0"))
                for point in no_periods.savings_capacity.points
            ),
            protected_total=Decimal("0"),
        ),
    )

    expired_result = _optimize(no_periods)
    no_goal_result = _optimize(no_goals)
    no_capacity_result = _optimize(no_capacity)

    assert expired_result.reason_codes == (
        OptimizationReasonCode.NO_FEASIBLE_ALLOCATION_PERIODS,
    )
    assert no_goal_result.reason_codes == (OptimizationReasonCode.NO_ELIGIBLE_GOALS,)
    assert no_capacity_result.reason_codes == (
        OptimizationReasonCode.NO_PROTECTED_CAPACITY,
    )


def test_exact_invariant_checker_detects_every_material_schedule_violation() -> None:
    goal = _goal(name="Goal", target="100", priority=GoalPriority.HIGH)
    snapshot = _snapshot((goal,))
    ranking = analyze_goal_planning_snapshot(snapshot).ranking
    unknown_id = uuid4()
    bad_periods = (
        MonthlyAllocationPeriod(
            period_start=date(2026, 10, 1),
            available_capacity=Decimal("50.0000"),
            allocated_amount=Decimal("151.0000"),
            unallocated_amount=Decimal("0.0000"),
            allocations=(
                GoalMonthlyAllocation(goal.goal_id, 99, Decimal("150.0000")),
                GoalMonthlyAllocation(goal.goal_id, 1, Decimal("0.0000")),
                GoalMonthlyAllocation(unknown_id, 1, Decimal("1.0000")),
            ),
        ),
        MonthlyAllocationPeriod(
            period_start=date(2027, 1, 1),
            available_capacity=Decimal("50.0000"),
            allocated_amount=Decimal("1.0000"),
            unallocated_amount=Decimal("49.0000"),
            allocations=(
                GoalMonthlyAllocation(goal.goal_id, 1, Decimal("1.0000")),
            ),
        ),
    )

    report = verify_allocation_invariants(
        snapshot=snapshot,
        ranking=ranking,
        periods=bad_periods,
        emergency_reserve_amount=Decimal("100"),
    )

    assert report.valid is False
    assert report.checked_allocation_count == 4
    assert set(report.violations) >= {
        AllocationInvariantViolation.CAPACITY_PERIOD_MISMATCH,
        AllocationInvariantViolation.PERIOD_TOTAL_MISMATCH,
        AllocationInvariantViolation.MONTHLY_CAPACITY_EXCEEDED,
        AllocationInvariantViolation.UNKNOWN_GOAL,
        AllocationInvariantViolation.RANK_MISMATCH,
        AllocationInvariantViolation.DUPLICATE_GOAL_ALLOCATION,
        AllocationInvariantViolation.NON_POSITIVE_ALLOCATION,
        AllocationInvariantViolation.GOAL_LIMIT_EXCEEDED,
        AllocationInvariantViolation.DEADLINE_EXCEEDED,
        AllocationInvariantViolation.EMERGENCY_RESERVE_EXCEEDED,
        AllocationInvariantViolation.AGGREGATE_TOTAL_MISMATCH,
    }


def test_invalid_emergency_reserve_is_rejected() -> None:
    snapshot = _snapshot(
        (_goal(name="Goal", target="100", priority=GoalPriority.HIGH),)
    )

    for invalid in (Decimal("-1"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError, match="finite and non-negative"):
            _optimize(snapshot, emergency_reserve_amount=invalid)


def test_scipy_adapter_reports_import_and_runtime_failures(monkeypatch) -> None:
    original_import = builtins.__import__

    def unavailable_import(name, *args, **kwargs):
        if name == "scipy":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable_import)
    unavailable = SciPyHighsSolver().solve(
        objective=(-1.0,),
        upper_bound_matrix=((1.0,),),
        upper_bounds=(1.0,),
        bounds=((0.0, 1.0),),
    )
    assert unavailable.status is LinearSolverStatus.UNAVAILABLE
    monkeypatch.setattr(builtins, "__import__", original_import)

    import scipy.optimize

    def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("provider exploded " + "x" * 300)

    monkeypatch.setattr(scipy.optimize, "linprog", fail)
    failed = SciPyHighsSolver().solve(
        objective=(-1.0,),
        upper_bound_matrix=((1.0,),),
        upper_bounds=(1.0,),
        bounds=((0.0, 1.0),),
    )
    assert failed.status is LinearSolverStatus.FAILED
    assert len(failed.message) == 240
