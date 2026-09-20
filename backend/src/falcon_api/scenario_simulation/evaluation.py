"""Phase 10 policy reuse for deterministic Phase 11 goal-plan reevaluation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID

from falcon_api.analytics.types import MONEY_QUANTUM, money
from falcon_api.goal_planning.capacity import SavingsCapacityPlan, SavingsCapacityPoint
from falcon_api.goal_planning.feasibility import (
    GoalFeasibilityAssessment,
    assess_snapshot_feasibility,
)
from falcon_api.goal_planning.greedy import (
    GoalAllocationProjection,
    GoalMonthlyAllocation,
    MonthlyAllocationPeriod,
)
from falcon_api.goal_planning.optimizer import (
    AllocationInvariantViolation,
    ConstrainedOptimizationResult,
    ConstrainedOptimizationStatus,
    GoalAllocationBound,
    LinearProgramSolver,
    build_allocation_projections,
    calculate_weighted_funding_score,
    optimize_goal_allocations,
    verify_allocation_invariants,
)
from falcon_api.goal_planning.progress import (
    PROGRESS_RATIO_QUANTUM,
    GoalFundingState,
    GoalProgress,
    months_until_deadline,
)
from falcon_api.goal_planning.ranking import GoalRanking, rank_goal_assessments
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningBudgetEvidence,
    PlanningFinancialEvidence,
    PlanningProvenance,
)
from falcon_api.models.enums import GoalPriority, GoalType
from falcon_api.scenario_simulation.assumptions import GoalScenarioAdjustment
from falcon_api.scenario_simulation.paths import (
    DeterministicScenarioPath,
    build_deterministic_scenario_paths,
)
from falcon_api.scenario_simulation.semantics import (
    SCENARIO_REEVALUATION_POLICY_VERSION,
    ScenarioEvaluationStatus,
    ScenarioPathStatus,
    ScenarioReasonCode,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceSnapshot


@dataclass(frozen=True, slots=True)
class ScenarioGoalEvaluation:
    """One Phase 10-compatible goal outcome under a deterministic scenario."""

    goal_id: UUID
    rank: int
    feasibility_state: str
    deadline_risk: str
    completion_probability: Decimal | None
    protected_shortfall: Decimal
    expected_shortfall: Decimal
    projected_completion_period: date | None
    projected_remaining_amount: Decimal
    allocated_amount: Decimal
    deadline_met: bool


@dataclass(frozen=True, slots=True)
class ScenarioPlanComparison:
    """Exact change from the immutable Phase 10 source plan."""

    source_allocated_total: Decimal
    scenario_allocated_total: Decimal
    allocated_delta: Decimal
    source_weighted_funding_score: Decimal
    scenario_weighted_funding_score: Decimal
    weighted_score_delta: Decimal
    source_fully_funded_goal_count: int
    scenario_fully_funded_goal_count: int
    fully_funded_goal_delta: int
    source_deadline_met_goal_count: int
    scenario_deadline_met_goal_count: int
    deadline_met_goal_delta: int


@dataclass(frozen=True, slots=True)
class DeterministicScenarioEvaluation:
    """Safe non-persistent goal-plan reevaluation for one deterministic path."""

    evaluation_id: str
    snapshot_id: str
    path_id: str
    policy_version: str
    name: str
    kind: str
    status: ScenarioEvaluationStatus
    selected_band: str
    emergency_reserve_amount: Decimal
    capacity_total: Decimal
    allocated_total: Decimal
    unallocated_total: Decimal
    weighted_funding_score: Decimal
    periods: tuple[MonthlyAllocationPeriod, ...]
    goals: tuple[ScenarioGoalEvaluation, ...]
    assessments: tuple[GoalFeasibilityAssessment, ...]
    ranking: GoalRanking | None
    optimizer_candidate: ConstrainedOptimizationResult | None
    comparison: ScenarioPlanComparison
    reserve_satisfied: bool
    reason_codes: tuple[ScenarioReasonCode, ...]


def evaluate_deterministic_scenarios(
    snapshot: ScenarioEvidenceSnapshot,
    *,
    solver: LinearProgramSolver | None = None,
) -> tuple[DeterministicScenarioEvaluation, ...]:
    """Reevaluate every reference and user alternative without persistence."""
    return tuple(
        _evaluate_path(snapshot=snapshot, path=path, solver=solver)
        for path in build_deterministic_scenario_paths(snapshot)
    )


def _evaluate_path(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
    solver: LinearProgramSolver | None,
) -> DeterministicScenarioEvaluation:
    if path.status is ScenarioPathStatus.UNAVAILABLE:
        return _unavailable(snapshot=snapshot, path=path)
    planning = _planning_snapshot(snapshot=snapshot, path=path)
    assessments = assess_snapshot_feasibility(
        planning.goals,
        planning.savings_capacity,
    )
    ranking = rank_goal_assessments(
        snapshot_id=planning.snapshot_id,
        goals=planning.goals,
        assessments=assessments,
    )
    bounds = _allocation_bounds(
        evidence=snapshot,
        path=path,
        planning=planning,
    )
    reasons = list(path.reason_codes)
    source_blocked = snapshot.source_plan.strategy == "blocked"
    capacity_empty = path.selected_total <= 0
    no_eligible = not any(item.eligible_for_allocation for item in ranking.items)
    if source_blocked or capacity_empty or no_eligible:
        if source_blocked:
            reasons.append(ScenarioReasonCode.SOURCE_PLAN_BLOCKED)
        if capacity_empty:
            reasons.append(ScenarioReasonCode.NO_PROTECTED_CAPACITY)
        if no_eligible:
            reasons.append(ScenarioReasonCode.NO_ELIGIBLE_GOALS)
        periods = _zero_periods(planning)
        projections = build_allocation_projections(
            snapshot=planning,
            ranking=ranking,
            periods=periods,
        )
        return _result(
            evidence=snapshot,
            path=path,
            planning=planning,
            assessments=assessments,
            ranking=ranking,
            optimizer=None,
            status=ScenarioEvaluationStatus.BLOCKED,
            periods=periods,
            projections=projections,
            reasons=tuple(reasons),
            bounds=bounds,
        )

    fallback = _guarded_bounded_greedy(
        snapshot=planning,
        ranking=ranking,
        reserve=path.emergency_reserve_amount,
        bounds=bounds,
    )
    optimizer = optimize_goal_allocations(
        snapshot=planning,
        ranking=ranking,
        emergency_reserve_amount=path.emergency_reserve_amount,
        allocation_bounds=bounds,
        solver=solver,
    )
    if fallback is None:
        reasons.append(ScenarioReasonCode.CONTRIBUTION_CONSTRAINT_INFEASIBLE)
        return _result(
            evidence=snapshot,
            path=path,
            planning=planning,
            assessments=assessments,
            ranking=ranking,
            optimizer=optimizer,
            status=ScenarioEvaluationStatus.INFEASIBLE,
            periods=_zero_periods(planning),
            projections=build_allocation_projections(
                snapshot=planning,
                ranking=ranking,
                periods=_zero_periods(planning),
            ),
            reasons=tuple(reasons),
            bounds=(),
        )

    fallback_projections = build_allocation_projections(
        snapshot=planning,
        ranking=ranking,
        periods=fallback,
    )
    fallback_score = calculate_weighted_funding_score(
        ranking=ranking,
        projections=fallback_projections,
    )
    if (
        optimizer.status is ConstrainedOptimizationStatus.OPTIMAL
        and optimizer.weighted_funding_score is not None
        and optimizer.weighted_funding_score >= fallback_score
    ):
        status = ScenarioEvaluationStatus.OPTIMIZED
        periods = optimizer.periods
        projections = optimizer.goal_projections
        reasons.append(ScenarioReasonCode.OPTIMIZED_SCHEDULE_SELECTED)
    else:
        status = ScenarioEvaluationStatus.GUARDED_FALLBACK
        periods = fallback
        projections = fallback_projections
        reasons.append(ScenarioReasonCode.GUARDED_FALLBACK_SELECTED)
    return _result(
        evidence=snapshot,
        path=path,
        planning=planning,
        assessments=assessments,
        ranking=ranking,
        optimizer=optimizer,
        status=status,
        periods=periods,
        projections=projections,
        reasons=tuple(reasons),
        bounds=bounds,
    )


def _planning_snapshot(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
) -> GoalPlanningSnapshot:
    adjustments = {
        item.goal_id: item
        for item in (
            path.assumptions.goal_adjustments
            if path.assumptions is not None
            else ()
        )
    }
    goals = tuple(
        _goal_progress(
            goal=goal,
            adjustment=adjustments.get(goal.goal_id),
            calculated_on=snapshot.local_date,
            currency=snapshot.currency,
        )
        for goal in snapshot.goals
    )
    points = tuple(
        SavingsCapacityPoint(
            period_start=item.period_start,
            protected_amount=money(item.selected_capacity),
            expected_amount=money(max(item.selected_capacity, item.expected_amount)),
            upside_amount=money(max(item.selected_capacity, item.upside_amount)),
        )
        for item in path.periods
    )
    capacity = SavingsCapacityPlan(
        forecast_run_id=(
            snapshot.forecast.run_id
            if snapshot.forecast is not None
            else snapshot.source_plan.run_id
        ),
        currency=snapshot.currency,
        policy_version=path.policy_version,
        protection_band=path.selected_band,
        reliability=(
            "provisional"
            if path.status is ScenarioPathStatus.LIMITED
            else "normal"
        ),
        points=points,
        protected_total=money(
            sum((item.protected_amount for item in points), Decimal(0))
        ),
        expected_total=money(
            sum((item.expected_amount for item in points), Decimal(0))
        ),
        upside_total=money(sum((item.upside_amount for item in points), Decimal(0))),
    )
    return GoalPlanningSnapshot(
        snapshot_id=path.path_id,
        contract_version=snapshot.contract_version,
        cutoff_at=snapshot.cutoff_at,
        local_date=snapshot.local_date,
        timezone=snapshot.timezone,
        currency=snapshot.currency,
        goals=goals,
        profile=None,
        finances=PlanningFinancialEvidence(
            liquid_balance=Decimal("0.0000"),
            liability_account_count=0,
            liability_payment_count=0,
            outstanding_debt=Decimal("0.0000"),
            monthly_debt_payment=Decimal("0.0000"),
            source_last_updated_at=None,
        ),
        budgets=PlanningBudgetEvidence(
            active_budget_count=0,
            budget_with_overall_limit_count=0,
            total_overall_limit=Decimal("0.0000"),
            source_last_updated_at=None,
        ),
        savings_capacity=capacity,
        warnings=(),
        provenance=PlanningProvenance(
            goal_ids=tuple(item.goal_id for item in goals),
            contribution_count=0,
            forecast_run_id=capacity.forecast_run_id,
            source_last_updated_at=None,
        ),
    )


def _goal_progress(
    *,
    goal: Any,
    adjustment: GoalScenarioAdjustment | None,
    calculated_on: date,
    currency: str,
) -> GoalProgress:
    target = money(
        adjustment.target_amount
        if adjustment is not None and adjustment.target_amount is not None
        else goal.target_amount
    )
    target_date = (
        adjustment.target_date
        if adjustment is not None and adjustment.target_date is not None
        else goal.target_date
    )
    priority = GoalPriority(
        adjustment.priority
        if adjustment is not None and adjustment.priority is not None
        else goal.priority
    )
    current = money(goal.current_amount)
    remaining = money(max(Decimal("0"), target - current))
    ratio = min(Decimal("1"), current / target).quantize(
        PROGRESS_RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
    months = months_until_deadline(
        calculated_on=calculated_on,
        target_date=target_date,
    )
    required = (
        Decimal("0.0000")
        if remaining == 0 or months == 0
        else (remaining / Decimal(months)).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_CEILING,
        )
    )
    state = (
        GoalFundingState.FUNDED
        if remaining == 0
        else GoalFundingState.OVERDUE
        if months == 0
        else GoalFundingState.NOT_STARTED
        if current == 0
        else GoalFundingState.IN_PROGRESS
    )
    return GoalProgress(
        goal_id=goal.goal_id,
        goal_name=goal.goal_name,
        goal_type=GoalType(goal.goal_type),
        priority=priority,
        target_date=target_date,
        currency=currency,
        target_amount=target,
        starting_amount=current,
        contribution_amount=Decimal("0.0000"),
        current_amount=current,
        remaining_amount=remaining,
        funding_ratio=ratio,
        funding_percentage=(ratio * Decimal("100")).quantize(Decimal("0.0001")),
        months_remaining=months,
        required_monthly_contribution=required,
        funding_state=state,
        calculated_on=calculated_on,
    )


def _allocation_bounds(
    *,
    evidence: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
    planning: GoalPlanningSnapshot,
) -> tuple[GoalAllocationBound, ...]:
    if path.assumptions is None:
        return ()
    source = {
        (allocation.goal_id, period.period_start): allocation.amount
        for period in evidence.periods
        for allocation in period.allocations
    }
    goals = {item.goal_id: item for item in planning.goals}
    bounds: list[GoalAllocationBound] = []
    for adjustment in path.assumptions.goal_adjustments:
        goal = goals[adjustment.goal_id]
        for period in path.periods:
            if period.period_start > goal.target_date:
                continue
            paused = (
                adjustment.pause_start is not None
                and adjustment.pause_end is not None
                and adjustment.pause_start
                <= period.period_start
                <= adjustment.pause_end
            )
            if paused:
                bounds.append(
                    GoalAllocationBound(
                        goal_id=goal.goal_id,
                        period_start=period.period_start,
                        maximum_amount=Decimal("0.0000"),
                    )
                )
                continue
            delta = adjustment.monthly_contribution_delta
            if delta is None:
                continue
            desired = money(
                max(
                    Decimal("0"),
                    source.get((goal.goal_id, period.period_start), Decimal("0"))
                    + delta,
                )
            )
            bounds.append(
                GoalAllocationBound(
                    goal_id=goal.goal_id,
                    period_start=period.period_start,
                    minimum_amount=desired if delta > 0 else Decimal("0.0000"),
                    maximum_amount=None if delta > 0 else desired,
                )
            )
    return tuple(bounds)


def _guarded_bounded_greedy(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
    reserve: Decimal,
    bounds: tuple[GoalAllocationBound, ...],
) -> tuple[MonthlyAllocationPeriod, ...] | None:
    assert snapshot.savings_capacity is not None
    goals = {item.goal_id: item for item in snapshot.goals}
    remaining = {item.goal_id: money(item.remaining_amount) for item in snapshot.goals}
    bound_map = {(item.goal_id, item.period_start): item for item in bounds}
    cumulative_capacity = Decimal("0.0000")
    cumulative_non_emergency = Decimal("0.0000")
    periods: list[MonthlyAllocationPeriod] = []
    for point in snapshot.savings_capacity.points:
        available = money(point.protected_amount)
        cumulative_capacity = money(cumulative_capacity + available)
        allocations: dict[UUID, Decimal] = {}
        for ranked in ranking.items:
            bound = bound_map.get((ranked.goal_id, point.period_start))
            minimum = bound.minimum_amount if bound is not None else Decimal("0")
            if minimum <= 0:
                continue
            goal = goals[ranked.goal_id]
            non_emergency_limit = money(
                max(Decimal("0"), cumulative_capacity - reserve)
            )
            if (
                minimum > available
                or minimum > remaining[ranked.goal_id]
                or (
                    goal.goal_type is not GoalType.EMERGENCY_FUND
                    and cumulative_non_emergency + minimum > non_emergency_limit
                )
            ):
                return None
            allocations[ranked.goal_id] = money(minimum)
            available = money(available - minimum)
            remaining[ranked.goal_id] = money(remaining[ranked.goal_id] - minimum)
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                cumulative_non_emergency = money(cumulative_non_emergency + minimum)

        for ranked in ranking.items:
            goal = goals[ranked.goal_id]
            if (
                available <= 0
                or not ranked.eligible_for_allocation
                or point.period_start > goal.target_date
                or remaining[ranked.goal_id] <= 0
            ):
                continue
            bound = bound_map.get((ranked.goal_id, point.period_start))
            maximum = (
                bound.maximum_amount
                if bound is not None and bound.maximum_amount is not None
                else remaining[ranked.goal_id]
                + allocations.get(ranked.goal_id, Decimal(0))
            )
            room = money(maximum - allocations.get(ranked.goal_id, Decimal(0)))
            if room <= 0:
                continue
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                non_emergency_limit = money(
                    max(Decimal("0"), cumulative_capacity - reserve)
                )
                room = min(
                    room,
                    money(
                        max(
                            Decimal("0"),
                            non_emergency_limit - cumulative_non_emergency,
                        )
                    ),
                )
            amount = money(min(available, remaining[ranked.goal_id], room))
            if amount <= 0:
                continue
            allocations[ranked.goal_id] = money(
                allocations.get(ranked.goal_id, Decimal("0")) + amount
            )
            available = money(available - amount)
            remaining[ranked.goal_id] = money(remaining[ranked.goal_id] - amount)
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                cumulative_non_emergency = money(cumulative_non_emergency + amount)
        ordered = tuple(
            GoalMonthlyAllocation(
                goal_id=item.goal_id,
                rank=item.rank,
                amount=allocations[item.goal_id],
            )
            for item in ranking.items
            if allocations.get(item.goal_id, Decimal("0")) > 0
        )
        allocated = money(sum((item.amount for item in ordered), Decimal("0")))
        periods.append(
            MonthlyAllocationPeriod(
                period_start=point.period_start,
                available_capacity=money(point.protected_amount),
                allocated_amount=allocated,
                unallocated_amount=money(point.protected_amount - allocated),
                allocations=ordered,
            )
        )
    result = tuple(periods)
    report = verify_allocation_invariants(
        snapshot=snapshot,
        ranking=ranking,
        periods=result,
        emergency_reserve_amount=reserve,
        allocation_bounds=bounds,
    )
    return result if report.valid else None


def _zero_periods(
    snapshot: GoalPlanningSnapshot,
) -> tuple[MonthlyAllocationPeriod, ...]:
    assert snapshot.savings_capacity is not None
    return tuple(
        MonthlyAllocationPeriod(
            period_start=item.period_start,
            available_capacity=money(item.protected_amount),
            allocated_amount=Decimal("0.0000"),
            unallocated_amount=money(item.protected_amount),
            allocations=(),
        )
        for item in snapshot.savings_capacity.points
    )


def _result(
    *,
    evidence: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
    planning: GoalPlanningSnapshot,
    assessments: tuple[GoalFeasibilityAssessment, ...],
    ranking: GoalRanking,
    optimizer: ConstrainedOptimizationResult | None,
    status: ScenarioEvaluationStatus,
    periods: tuple[MonthlyAllocationPeriod, ...],
    projections: tuple[GoalAllocationProjection, ...],
    reasons: tuple[ScenarioReasonCode, ...],
    bounds: tuple[GoalAllocationBound, ...],
) -> DeterministicScenarioEvaluation:
    report = verify_allocation_invariants(
        snapshot=planning,
        ranking=ranking,
        periods=periods,
        emergency_reserve_amount=path.emergency_reserve_amount,
        allocation_bounds=bounds,
    )
    projection_by_id = {item.goal_id: item for item in projections}
    assessment_by_id = {item.goal_id: item for item in assessments}
    goals = tuple(
        _goal_evaluation(
            ranked=ranked,
            assessment=assessment_by_id[ranked.goal_id],
            projection=projection_by_id[ranked.goal_id],
        )
        for ranked in ranking.items
    )
    allocated = money(sum((item.allocated_amount for item in periods), Decimal("0")))
    capacity = money(sum((item.available_capacity for item in periods), Decimal("0")))
    score = calculate_weighted_funding_score(ranking=ranking, projections=projections)
    comparison = _comparison(
        evidence=evidence,
        allocated=allocated,
        score=score,
        goals=goals,
    )
    payload = {
        "snapshot_id": evidence.snapshot_id,
        "path_id": path.path_id,
        "policy_version": SCENARIO_REEVALUATION_POLICY_VERSION,
        "status": status,
        "reserve": path.emergency_reserve_amount,
        "periods": periods,
        "goals": goals,
        "comparison": comparison,
        "reasons": reasons,
    }
    return DeterministicScenarioEvaluation(
        evaluation_id=_hash(payload),
        snapshot_id=evidence.snapshot_id,
        path_id=path.path_id,
        policy_version=SCENARIO_REEVALUATION_POLICY_VERSION,
        name=path.name,
        kind=path.kind.value,
        status=status,
        selected_band=path.selected_band,
        emergency_reserve_amount=path.emergency_reserve_amount,
        capacity_total=capacity,
        allocated_total=allocated,
        unallocated_total=money(capacity - allocated),
        weighted_funding_score=score,
        periods=periods,
        goals=goals,
        assessments=assessments,
        ranking=ranking,
        optimizer_candidate=optimizer,
        comparison=comparison,
        reserve_satisfied=(
            AllocationInvariantViolation.EMERGENCY_RESERVE_EXCEEDED
            not in report.violations
        ),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _unavailable(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
) -> DeterministicScenarioEvaluation:
    comparison = _comparison(
        evidence=snapshot,
        allocated=Decimal(0),
        score=Decimal(0),
        goals=(),
    )
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "path_id": path.path_id,
        "status": ScenarioEvaluationStatus.UNAVAILABLE,
        "reasons": path.reason_codes,
    }
    return DeterministicScenarioEvaluation(
        evaluation_id=_hash(payload),
        snapshot_id=snapshot.snapshot_id,
        path_id=path.path_id,
        policy_version=SCENARIO_REEVALUATION_POLICY_VERSION,
        name=path.name,
        kind=path.kind.value,
        status=ScenarioEvaluationStatus.UNAVAILABLE,
        selected_band=path.selected_band,
        emergency_reserve_amount=path.emergency_reserve_amount,
        capacity_total=Decimal("0.0000"),
        allocated_total=Decimal("0.0000"),
        unallocated_total=Decimal("0.0000"),
        weighted_funding_score=Decimal("0.0000"),
        periods=(),
        goals=(),
        assessments=(),
        ranking=None,
        optimizer_candidate=None,
        comparison=comparison,
        reserve_satisfied=False,
        reason_codes=path.reason_codes,
    )


def _goal_evaluation(
    *,
    ranked: Any,
    assessment: Any,
    projection: Any,
) -> ScenarioGoalEvaluation:
    return ScenarioGoalEvaluation(
        goal_id=ranked.goal_id,
        rank=ranked.rank,
        feasibility_state=assessment.feasibility_state.value,
        deadline_risk=assessment.deadline_risk.value,
        completion_probability=assessment.completion_probability,
        protected_shortfall=assessment.protected_shortfall,
        expected_shortfall=assessment.expected_shortfall,
        projected_completion_period=projection.projected_completion_period,
        projected_remaining_amount=projection.projected_remaining_amount,
        allocated_amount=projection.allocated_amount,
        deadline_met=projection.deadline_met,
    )


def _comparison(
    *,
    evidence: ScenarioEvidenceSnapshot,
    allocated: Decimal,
    score: Decimal,
    goals: tuple[ScenarioGoalEvaluation, ...],
) -> ScenarioPlanComparison:
    source_funded = sum(item.projected_remaining_amount == 0 for item in evidence.goals)
    source_deadline = sum(item.deadline_met for item in evidence.goals)
    scenario_funded = sum(item.projected_remaining_amount == 0 for item in goals)
    scenario_deadline = sum(item.deadline_met for item in goals)
    source_allocated = money(evidence.source_plan.allocated_savings)
    source_score = Decimal(evidence.source_plan.weighted_funding_score)
    return ScenarioPlanComparison(
        source_allocated_total=source_allocated,
        scenario_allocated_total=money(allocated),
        allocated_delta=money(allocated - source_allocated),
        source_weighted_funding_score=source_score,
        scenario_weighted_funding_score=score,
        weighted_score_delta=(score - source_score).quantize(Decimal("0.0001")),
        source_fully_funded_goal_count=source_funded,
        scenario_fully_funded_goal_count=scenario_funded,
        fully_funded_goal_delta=scenario_funded - source_funded,
        source_deadline_met_goal_count=source_deadline,
        scenario_deadline_met_goal_count=scenario_deadline,
        deadline_met_goal_delta=scenario_deadline - source_deadline,
    )


def _hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported scenario evaluation value: {type(value).__name__}")
