"""Checkpoint 10.11 unified schedule, comparison, and fallback tests."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from falcon_api.goal_planning import (
    GOAL_OPTIMIZATION_PLAN_POLICY_VERSION,
    ConstrainedOptimizationStatus,
    GoalPlanAssumption,
    GoalPlanReasonCode,
    GoalPlanStrategy,
    LinearProgramSolution,
    LinearSolverStatus,
    SavingsCapacityPlan,
    SavingsCapacityPoint,
    build_goal_optimization_plan,
    calculate_goal_progress,
)
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningBudgetEvidence,
    PlanningFinancialEvidence,
    PlanningProfileEvidence,
    PlanningProvenance,
    PlanningSnapshotWarning,
)
from falcon_api.models.enums import (
    GoalPriority,
    GoalStatus,
    GoalType,
    ProfileCompletionStatus,
)
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class _ZeroSolver:
    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del upper_bound_matrix, upper_bounds, bounds
        return LinearProgramSolution(
            status=LinearSolverStatus.OPTIMAL,
            values=tuple(0.0 for _ in objective),
            objective_value=0.0,
            solver_name="zero_test_solver",
            solver_version="1",
            message="valid but useless",
            iterations=0,
        )


class _UnavailableSolver:
    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del objective, upper_bound_matrix, upper_bounds, bounds
        return LinearProgramSolution(
            status=LinearSolverStatus.UNAVAILABLE,
            values=(),
            objective_value=None,
            solver_name="missing_test_solver",
            solver_version=None,
            message="missing",
            iterations=None,
        )


class _InvalidSolver:
    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del upper_bound_matrix, upper_bounds, bounds
        return LinearProgramSolution(
            status=LinearSolverStatus.OPTIMAL,
            values=tuple(float("nan") for _ in objective),
            objective_value=None,
            solver_name="invalid_test_solver",
            solver_version="1",
            message="invalid",
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
    liquid_balance: str = "2000",
    liabilities: int = 0,
    liability_payments: int = 0,
    budget_limit: str = "500",
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
    goal_tuple = tuple(goals)
    return GoalPlanningSnapshot(
        snapshot_id="c" * 64,
        contract_version="2026.1",
        cutoff_at=_NOW,
        local_date=date(2026, 9, 15),
        timezone="Asia/Kolkata",
        currency="INR",
        goals=goal_tuple,
        profile=PlanningProfileEvidence(
            completion_status=ProfileCompletionStatus.COMPLETE,
            income_stability="stable",
            emergency_fund_target_months=Decimal("3"),
            updated_at=_NOW,
        ),
        finances=PlanningFinancialEvidence(
            liquid_balance=Decimal(liquid_balance),
            liability_account_count=liabilities,
            liability_payment_count=liability_payments,
            outstanding_debt=Decimal("1000" if liabilities else "0"),
            monthly_debt_payment=Decimal("100" if liability_payments else "0"),
            source_last_updated_at=_NOW,
        ),
        budgets=PlanningBudgetEvidence(
            active_budget_count=1,
            budget_with_overall_limit_count=1,
            total_overall_limit=Decimal(budget_limit),
            source_last_updated_at=_NOW,
        ),
        savings_capacity=capacity,
        warnings=(
            (PlanningSnapshotWarning.DEBT_PAYMENT_INCOMPLETE,)
            if liabilities != liability_payments
            else ()
        ),
        provenance=PlanningProvenance(
            goal_ids=tuple(goal.goal_id for goal in goal_tuple),
            contribution_count=0,
            forecast_run_id=capacity.forecast_run_id,
            source_last_updated_at=_NOW,
        ),
    )


def test_unified_plan_selects_better_highs_schedule_and_is_deterministic() -> None:
    large = _goal(
        goal_id=UUID(int=1),
        name="Large critical goal",
        target="1000",
        priority=GoalPriority.CRITICAL,
    )
    small = _goal(
        goal_id=UUID(int=2),
        name="Small goal",
        target="100",
        priority=GoalPriority.LOW,
    )
    snapshot = _snapshot((large, small))

    first = build_goal_optimization_plan(snapshot)
    second = build_goal_optimization_plan(snapshot)

    assert first == second
    assert len(first.plan_id) == 64
    assert first.policy_version == GOAL_OPTIMIZATION_PLAN_POLICY_VERSION == "2026.1"
    assert first.schedule.strategy is GoalPlanStrategy.OPTIMIZED
    assert first.schedule.invariants.valid is True
    assert first.optimizer_candidate is not None
    assert first.optimizer_candidate.status is ConstrainedOptimizationStatus.OPTIMAL
    assert first.comparison.optimized_score_delta_from_greedy > 0
    assert first.comparison.selected_score_delta_from_greedy > 0
    assert first.reason_codes == (GoalPlanReasonCode.OPTIMIZED_PLAN_SELECTED,)
    assert first.assumptions == tuple(GoalPlanAssumption)


def test_emergency_gap_makes_unsafe_baseline_visible_and_reserves_capacity() -> None:
    travel = _goal(
        name="Travel",
        target="1000",
        priority=GoalPriority.CRITICAL,
        goal_type=GoalType.TRAVEL,
    )
    snapshot = _snapshot(
        (travel,),
        liquid_balance="900",
        amounts=("500", "500"),
    )

    result = build_goal_optimization_plan(snapshot)

    assert result.guardrails.emergency_reserve_amount == Decimal("600.0000")
    assert result.comparison.greedy_baseline_guardrail_compliant is False
    assert result.schedule.allocated_total <= Decimal("400.0000")
    assert result.schedule.unallocated_total >= Decimal("600.0000")
    assert result.schedule.invariants.valid is True
    assert GoalPlanReasonCode.EMERGENCY_RESERVE_APPLIED in result.reason_codes


def test_incomplete_debt_evidence_blocks_solver_and_returns_zero_schedule() -> None:
    goal = _goal(
        name="Goal",
        target="100",
        priority=GoalPriority.HIGH,
    )
    snapshot = _snapshot((goal,), liabilities=2, liability_payments=1)

    result = build_goal_optimization_plan(snapshot)

    assert result.schedule.strategy is GoalPlanStrategy.BLOCKED
    assert result.optimizer_candidate is None
    assert result.schedule.allocated_total == Decimal("0.0000")
    assert result.schedule.unallocated_total == result.schedule.capacity_total
    assert result.schedule.invariants.valid is True
    assert result.reason_codes == (GoalPlanReasonCode.GUARDRAIL_BLOCKED,)
    assert result.comparison.optimizer_status is None


def test_unavailable_solver_uses_guarded_deterministic_fallback() -> None:
    goal = _goal(
        name="Goal",
        target="100",
        priority=GoalPriority.HIGH,
    )
    snapshot = _snapshot((goal,))

    first = build_goal_optimization_plan(snapshot, solver=_UnavailableSolver())
    second = build_goal_optimization_plan(snapshot, solver=_UnavailableSolver())

    assert first == second
    assert first.schedule.strategy is GoalPlanStrategy.GUARDED_GREEDY_FALLBACK
    assert first.schedule.allocated_total == Decimal("100.0000")
    assert first.reason_codes == (
        GoalPlanReasonCode.SOLVER_UNAVAILABLE_FALLBACK,
    )
    assert (
        first.comparison.optimizer_status
        is ConstrainedOptimizationStatus.SOLVER_UNAVAILABLE
    )


@pytest.mark.parametrize(
    ("solver", "reason"),
    [
        (_InvalidSolver(), GoalPlanReasonCode.INVALID_SOLUTION_FALLBACK),
        (_ZeroSolver(), GoalPlanReasonCode.GUARDED_FALLBACK_OUTPERFORMED),
    ],
)
def test_invalid_or_underperforming_candidates_never_replace_safe_fallback(
    solver,
    reason,
) -> None:
    goal = _goal(
        name="Goal",
        target="100",
        priority=GoalPriority.HIGH,
    )
    result = build_goal_optimization_plan(_snapshot((goal,)), solver=solver)

    assert result.schedule.strategy is GoalPlanStrategy.GUARDED_GREEDY_FALLBACK
    assert result.schedule.allocated_total == Decimal("100.0000")
    assert result.reason_codes == (reason,)


def test_no_feasible_forecast_period_uses_explicit_zero_fallback() -> None:
    goal = _goal(
        name="September goal",
        target="100",
        priority=GoalPriority.HIGH,
        deadline=date(2026, 9, 30),
    )
    snapshot = _snapshot(
        (goal,),
        periods=(date(2026, 10, 1), date(2026, 11, 1)),
    )

    result = build_goal_optimization_plan(snapshot)

    assert result.schedule.strategy is GoalPlanStrategy.GUARDED_GREEDY_FALLBACK
    assert result.schedule.allocated_total == Decimal("0.0000")
    assert result.optimizer_candidate is not None
    assert (
        result.optimizer_candidate.status
        is ConstrainedOptimizationStatus.NO_SOLUTION
    )
    assert result.reason_codes == (GoalPlanReasonCode.NO_SOLUTION_FALLBACK,)


def test_plan_id_changes_when_selected_schedule_or_snapshot_changes() -> None:
    goal = _goal(
        name="Goal",
        target="100",
        priority=GoalPriority.HIGH,
    )
    snapshot = _snapshot((goal,))

    optimized = build_goal_optimization_plan(snapshot)
    fallback = build_goal_optimization_plan(snapshot, solver=_UnavailableSolver())
    changed_snapshot = build_goal_optimization_plan(
        replace(snapshot, snapshot_id="d" * 64),
        solver=_UnavailableSolver(),
    )

    assert optimized.plan_id != fallback.plan_id
    assert fallback.plan_id != changed_snapshot.plan_id
