"""Tests for Phase 10 policy reuse in deterministic scenario reevaluation."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.goal_planning import (
    AllocationInvariantViolation,
    GoalAllocationBound,
    verify_allocation_invariants,
)
from falcon_api.scenario_simulation import (
    GoalScenarioAdjustment,
    RecurringExpenseAdjustment,
    ScenarioAssumptions,
    ScenarioEvaluationStatus,
    ScenarioReasonCode,
    evaluate_deterministic_scenarios,
)
from goal_plan_test_data import GOAL_ID, ZeroSolver, goal_plan_case
from scenario_test_data import transient_scenario_snapshot


def test_reference_cases_reuse_phase_10_ranking_optimizer_and_comparison() -> None:
    assumptions = ScenarioAssumptions(
        name="Small expense",
        one_time_expenses=(),
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                priority="critical",
            ),
        ),
    )
    snapshot = transient_scenario_snapshot((assumptions,))

    results = evaluate_deterministic_scenarios(snapshot, solver=ZeroSolver())

    assert len(results) == 4
    assert [item.capacity_total for item in results[:3]] == [
        Decimal("100.0000"),
        Decimal("150.0000"),
        Decimal("200.0000"),
    ]
    for result in results[:3]:
        assert result.status is ScenarioEvaluationStatus.GUARDED_FALLBACK
        assert result.allocated_total == Decimal("100.0000")
        assert result.goals[0].projected_remaining_amount == Decimal("0.0000")
        assert result.reserve_satisfied is True
        assert result.ranking is not None
        assert ScenarioReasonCode.GUARDED_FALLBACK_SELECTED in result.reason_codes
    assert evaluate_deterministic_scenarios(snapshot, solver=ZeroSolver()) == results


def test_contribution_decrease_and_pause_become_exact_optimizer_bounds() -> None:
    assumptions = ScenarioAssumptions(
        name="Pause then reduce",
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                target_amount=Decimal("120"),
                monthly_contribution_delta=Decimal("-20"),
                pause_start=date(2026, 10, 1),
                pause_end=date(2026, 10, 1),
            ),
        ),
    )
    snapshot = transient_scenario_snapshot((assumptions,))

    result = evaluate_deterministic_scenarios(snapshot, solver=ZeroSolver())[3]

    assert result.status is ScenarioEvaluationStatus.GUARDED_FALLBACK
    assert result.periods[0].allocations == ()
    assert result.periods[1].allocations[0].amount == Decimal("30.0000")
    assert result.allocated_total == Decimal("30.0000")
    assert result.goals[0].projected_remaining_amount == Decimal("90.0000")
    assert result.comparison.allocated_delta == Decimal("-70.0000")
    assert ScenarioReasonCode.CONTRIBUTION_CONSTRAINT_APPLIED in result.reason_codes


def test_impossible_contribution_increase_is_reported_not_silently_relaxed() -> None:
    assumptions = ScenarioAssumptions(
        name="Impossible contribution",
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                monthly_contribution_delta=Decimal("1000"),
            ),
        ),
    )
    snapshot = transient_scenario_snapshot((assumptions,))

    result = evaluate_deterministic_scenarios(snapshot, solver=ZeroSolver())[3]

    assert result.status is ScenarioEvaluationStatus.INFEASIBLE
    assert result.allocated_total == Decimal("0.0000")
    assert ScenarioReasonCode.CONTRIBUTION_CONSTRAINT_INFEASIBLE in result.reason_codes


def test_real_highs_path_honors_feasible_contribution_increases() -> None:
    assumptions = ScenarioAssumptions(
        name="Increase contributions",
        recurring_expense_adjustments=(
            RecurringExpenseAdjustment(
                start_period=date(2026, 10, 1),
                end_period=date(2026, 11, 1),
                monthly_delta=Decimal("-20"),
            ),
        ),
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                target_amount=Decimal("150"),
                monthly_contribution_delta=Decimal("10"),
            ),
        ),
    )
    snapshot = transient_scenario_snapshot((assumptions,))

    result = evaluate_deterministic_scenarios(snapshot)[3]

    assert result.status is ScenarioEvaluationStatus.OPTIMIZED
    assert [period.allocations[0].amount for period in result.periods] == [
        Decimal("70.0000"),
        Decimal("70.0000"),
    ]
    assert result.optimizer_candidate is not None
    assert result.optimizer_candidate.invariants.valid is True


def test_phase_10_invariant_verifier_enforces_downstream_allocation_bounds() -> None:
    snapshot, plan = goal_plan_case()
    bound = GoalAllocationBound(
        goal_id=GOAL_ID,
        period_start=date(2026, 10, 1),
        minimum_amount=Decimal("60"),
    )

    report = verify_allocation_invariants(
        snapshot=snapshot,
        ranking=plan.analysis.ranking,
        periods=plan.schedule.periods,
        allocation_bounds=(bound,),
    )

    assert report.valid is False
    assert AllocationInvariantViolation.ALLOCATION_BOUND_VIOLATION in report.violations


def test_unavailable_and_blocked_paths_return_safe_non_persistent_results() -> None:
    unavailable = ScenarioAssumptions(
        name="Missing income evidence",
        income_change_percent=Decimal("-10"),
    )
    missing = transient_scenario_snapshot(
        (unavailable,),
        include_supplemental=False,
    )

    unavailable_result = evaluate_deterministic_scenarios(
        missing,
        solver=ZeroSolver(),
    )[3]

    assert unavailable_result.status is ScenarioEvaluationStatus.UNAVAILABLE
    assert unavailable_result.periods == ()
    assert unavailable_result.ranking is None
    assert unavailable_result.reserve_satisfied is False

    available = transient_scenario_snapshot((unavailable,))
    blocked = replace(
        available,
        source_plan=replace(available.source_plan, strategy="blocked"),
    )

    blocked_result = evaluate_deterministic_scenarios(
        blocked,
        solver=ZeroSolver(),
    )[0]

    assert blocked_result.status is ScenarioEvaluationStatus.BLOCKED
    assert blocked_result.allocated_total == Decimal("0.0000")
    assert blocked_result.reserve_satisfied is True
    assert ScenarioReasonCode.SOURCE_PLAN_BLOCKED in blocked_result.reason_codes


@pytest.mark.parametrize(
    "bound",
    [
        GoalAllocationBound(
            goal_id=uuid4(),
            period_start=date(2026, 10, 1),
        ),
        GoalAllocationBound(
            goal_id=GOAL_ID,
            period_start=date(2026, 10, 1),
            minimum_amount=Decimal("10"),
            maximum_amount=Decimal("5"),
        ),
    ],
)
def test_phase_10_allocation_bounds_reject_unknown_or_unordered_values(
    bound: GoalAllocationBound,
) -> None:
    snapshot, plan = goal_plan_case()

    with pytest.raises(ValueError, match="Allocation bounds"):
        verify_allocation_invariants(
            snapshot=snapshot,
            ranking=plan.analysis.ranking,
            periods=plan.schedule.periods,
            allocation_bounds=(bound,),
        )


def test_phase_10_allocation_bounds_are_unique_by_goal_and_period() -> None:
    snapshot, plan = goal_plan_case()
    bound = GoalAllocationBound(
        goal_id=GOAL_ID,
        period_start=date(2026, 10, 1),
    )

    with pytest.raises(ValueError, match="unique"):
        verify_allocation_invariants(
            snapshot=snapshot,
            ranking=plan.analysis.ranking,
            periods=plan.schedule.periods,
            allocation_bounds=(bound, bound),
        )
