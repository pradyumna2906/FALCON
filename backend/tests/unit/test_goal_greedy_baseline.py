"""Checkpoint 10.8 deterministic greedy allocation baseline tests."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.goal_planning import (
    GREEDY_ALLOCATION_POLICY_VERSION,
    GreedyBaselineWarning,
    SavingsCapacityPlan,
    SavingsCapacityPoint,
    analyze_goal_planning_snapshot,
    assess_snapshot_feasibility,
    build_greedy_allocation_baseline,
    calculate_goal_progress,
    rank_goal_assessments,
)
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningBudgetEvidence,
    PlanningFinancialEvidence,
    PlanningProvenance,
    PlanningSnapshotWarning,
)
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def _progress(
    *,
    name: str,
    target: str,
    priority: GoalPriority,
    deadline: date = date(2026, 12, 31),
):
    goal = Goal(
        id=uuid4(),
        user_id=uuid4(),
        name=name,
        goal_type=GoalType.OTHER,
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
        goal=goal,
        contribution_amount=Decimal("0"),
        calculated_on=date(2026, 9, 15),
    )


def _capacity(
    *,
    points: tuple[SavingsCapacityPoint, ...] | None = None,
    currency: str = "INR",
) -> SavingsCapacityPlan:
    resolved = points or (
        SavingsCapacityPoint(
            period_start=date(2026, 10, 1),
            protected_amount=Decimal("1000"),
            expected_amount=Decimal("1200"),
            upside_amount=Decimal("1500"),
        ),
        SavingsCapacityPoint(
            period_start=date(2026, 11, 1),
            protected_amount=Decimal("1000"),
            expected_amount=Decimal("1200"),
            upside_amount=Decimal("1500"),
        ),
    )
    return SavingsCapacityPlan(
        forecast_run_id=uuid4(),
        currency=currency,
        policy_version="2026.1",
        protection_band="95_percent",
        reliability="normal",
        points=resolved,
        protected_total=sum((item.protected_amount for item in resolved), Decimal(0)),
        expected_total=sum((item.expected_amount for item in resolved), Decimal(0)),
        upside_total=sum((item.upside_amount for item in resolved), Decimal(0)),
    )


def _snapshot(
    goals,
    *,
    capacity: SavingsCapacityPlan | None,
    snapshot_id: str = "a" * 64,
) -> GoalPlanningSnapshot:
    return GoalPlanningSnapshot(
        snapshot_id=snapshot_id,
        contract_version="2026.1",
        cutoff_at=_NOW,
        local_date=date(2026, 9, 15),
        timezone="Asia/Kolkata",
        currency="INR",
        goals=goals,
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
            forecast_run_id=capacity.forecast_run_id if capacity else None,
            source_last_updated_at=_NOW,
        ),
    )


def _ranking(snapshot: GoalPlanningSnapshot):
    assessments = assess_snapshot_feasibility(
        snapshot.goals,
        snapshot.savings_capacity,
    )
    return rank_goal_assessments(
        snapshot_id=snapshot.snapshot_id,
        goals=snapshot.goals,
        assessments=assessments,
    )


def test_greedy_baseline_consumes_capacity_once_in_rank_order() -> None:
    high = _progress(
        name="High",
        target="700",
        priority=GoalPriority.CRITICAL,
    )
    low = _progress(
        name="Low",
        target="800",
        priority=GoalPriority.LOW,
    )
    snapshot = _snapshot((low, high), capacity=_capacity())

    result = build_greedy_allocation_baseline(
        snapshot=snapshot,
        ranking=_ranking(snapshot),
    )

    assert result.policy_version == GREEDY_ALLOCATION_POLICY_VERSION == "2026.1"
    assert len(result.baseline_id) == 64
    assert result.allocation_band == "protected_95_percent_lower"
    assert result.capacity_total == Decimal("2000.0000")
    assert result.allocated_total == Decimal("1500.0000")
    assert result.unallocated_total == Decimal("500.0000")
    assert result.periods[0].allocations[0].goal_id == high.goal_id
    assert result.periods[0].allocations[0].amount == Decimal("700.0000")
    assert result.periods[0].allocations[1].goal_id == low.goal_id
    assert result.periods[0].allocations[1].amount == Decimal("300.0000")
    assert sum(
        (item.amount for period in result.periods for item in period.allocations),
        Decimal("0"),
    ) == result.allocated_total
    assert all(item.deadline_met for item in result.goal_projections)
    assert result.warnings == (GreedyBaselineWarning.CAPACITY_LEFT_UNALLOCATED,)


def test_greedy_baseline_never_allocates_after_goal_deadline() -> None:
    goal = _progress(
        name="September goal",
        target="500",
        priority=GoalPriority.HIGH,
        deadline=date(2026, 9, 30),
    )
    snapshot = _snapshot((goal,), capacity=_capacity())

    result = build_greedy_allocation_baseline(
        snapshot=snapshot,
        ranking=_ranking(snapshot),
    )

    assert result.allocated_total == Decimal("0.0000")
    assert result.unallocated_total == Decimal("2000.0000")
    assert result.goal_projections[0].projected_remaining_amount == Decimal("500.0000")
    assert result.goal_projections[0].deadline_met is False
    assert GreedyBaselineWarning.GOALS_REMAIN_UNFUNDED in result.warnings


def test_missing_capacity_returns_a_safe_non_allocating_baseline() -> None:
    goal = _progress(name="Goal", target="500", priority=GoalPriority.MEDIUM)
    snapshot = _snapshot((goal,), capacity=None)

    result = build_greedy_allocation_baseline(
        snapshot=snapshot,
        ranking=_ranking(snapshot),
    )

    assert result.periods == ()
    assert result.capacity_total == Decimal("0.0000")
    assert result.capacity_policy_version is None
    assert result.warnings == (
        GreedyBaselineWarning.CAPACITY_MISSING,
        GreedyBaselineWarning.GOALS_REMAIN_UNFUNDED,
    )


def test_no_goals_leaves_capacity_unallocated_with_explicit_warnings() -> None:
    snapshot = _snapshot((), capacity=_capacity())

    result = build_greedy_allocation_baseline(
        snapshot=snapshot,
        ranking=_ranking(snapshot),
    )

    assert result.goal_projections == ()
    assert result.warnings == (
        GreedyBaselineWarning.NO_ELIGIBLE_GOALS,
        GreedyBaselineWarning.CAPACITY_LEFT_UNALLOCATED,
    )


def test_provisional_capacity_and_snapshot_gaps_remain_visible() -> None:
    goal = _progress(name="Goal", target="500", priority=GoalPriority.HIGH)
    capacity = replace(_capacity(), reliability="provisional")
    snapshot = replace(
        _snapshot((goal,), capacity=capacity),
        warnings=(PlanningSnapshotWarning.PROFILE_MISSING,),
    )

    result = build_greedy_allocation_baseline(
        snapshot=snapshot,
        ranking=_ranking(snapshot),
    )

    assert result.warnings[:2] == (
        GreedyBaselineWarning.CAPACITY_PROVISIONAL,
        GreedyBaselineWarning.SNAPSHOT_EVIDENCE_INCOMPLETE,
    )


def test_analysis_orchestrator_is_deterministic_and_snapshot_bound() -> None:
    goal = _progress(name="Goal", target="500", priority=GoalPriority.HIGH)
    snapshot = _snapshot((goal,), capacity=_capacity())

    first = analyze_goal_planning_snapshot(snapshot)
    second = analyze_goal_planning_snapshot(snapshot)

    assert first == second
    assert first.snapshot_id == snapshot.snapshot_id
    assert first.ranking.items[0].goal_id == goal.goal_id
    assert first.greedy_baseline.baseline_id == second.greedy_baseline.baseline_id


def test_baseline_rejects_snapshot_and_ranking_mismatch() -> None:
    goal = _progress(name="Goal", target="500", priority=GoalPriority.HIGH)
    snapshot = _snapshot((goal,), capacity=_capacity())
    ranking = _ranking(snapshot)

    with pytest.raises(ValueError, match="identifiers"):
        build_greedy_allocation_baseline(
            snapshot=replace(snapshot, snapshot_id="b" * 64),
            ranking=ranking,
        )
    with pytest.raises(ValueError, match="every snapshot goal"):
        build_greedy_allocation_baseline(
            snapshot=snapshot,
            ranking=replace(ranking, items=()),
        )
    invalid_rank = replace(ranking.items[0], rank=2)
    with pytest.raises(ValueError, match="contiguous"):
        build_greedy_allocation_baseline(
            snapshot=snapshot,
            ranking=replace(ranking, items=(invalid_rank,)),
        )
    invalid_eligibility = replace(
        ranking.items[0],
        eligible_for_allocation=False,
    )
    with pytest.raises(ValueError, match="eligibility"):
        build_greedy_allocation_baseline(
            snapshot=snapshot,
            ranking=replace(ranking, items=(invalid_eligibility,)),
        )
    with pytest.raises(ValueError, match="Snapshot goals must be unique"):
        build_greedy_allocation_baseline(
            snapshot=replace(snapshot, goals=(goal, goal)),
            ranking=ranking,
        )


@pytest.mark.parametrize(
    ("capacity", "message"),
    [
        (_capacity(currency="USD"), "currencies"),
        (
            _capacity(
                points=(
                    SavingsCapacityPoint(
                        date(2026, 10, 1),
                        Decimal("1"),
                        Decimal("2"),
                        Decimal("3"),
                    ),
                    SavingsCapacityPoint(
                        date(2026, 10, 1),
                        Decimal("1"),
                        Decimal("2"),
                        Decimal("3"),
                    ),
                )
            ),
            "unique",
        ),
        (
            _capacity(
                points=(
                    SavingsCapacityPoint(
                        date(2026, 9, 1),
                        Decimal("1"),
                        Decimal("2"),
                        Decimal("3"),
                    ),
                )
            ),
            "before the snapshot",
        ),
        (
            _capacity(
                points=(
                    SavingsCapacityPoint(
                        date(2026, 10, 1),
                        Decimal("-1"),
                        Decimal("2"),
                        Decimal("3"),
                    ),
                )
            ),
            "non-negative",
        ),
    ],
)
def test_baseline_rejects_unsafe_capacity(
    capacity: SavingsCapacityPlan,
    message: str,
) -> None:
    goal = _progress(name="Goal", target="500", priority=GoalPriority.HIGH)
    valid_snapshot = _snapshot((goal,), capacity=_capacity())
    unsafe_snapshot = replace(valid_snapshot, savings_capacity=capacity)

    with pytest.raises(ValueError, match=message):
        build_greedy_allocation_baseline(
            snapshot=unsafe_snapshot,
            ranking=_ranking(valid_snapshot),
        )
