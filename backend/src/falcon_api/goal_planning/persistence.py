"""Owner-scoped persistence for immutable goal plans and lifecycle events."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from falcon_api.analytics.types import money
from falcon_api.goal_planning.feasibility import GoalFeasibilityState
from falcon_api.goal_planning.optimizer import (
    CONSTRAINED_OPTIMIZATION_POLICY_VERSION,
    build_allocation_projections,
    calculate_weighted_funding_score,
    verify_allocation_invariants,
)
from falcon_api.goal_planning.plan import GoalOptimizationPlan
from falcon_api.goal_planning.snapshot import GoalPlanningSnapshot
from falcon_api.models.enums import GoalPlanEventSource, GoalPlanStatus
from falcon_api.models.goal_plan import (
    GoalPlanAllocation,
    GoalPlanEvent,
    GoalPlanOutcome,
    GoalPlanPeriod,
    GoalPlanRun,
)


MAX_GOAL_PLAN_HISTORY = 100

_FEASIBLE_STATES = frozenset(
    {
        GoalFeasibilityState.FUNDED,
        GoalFeasibilityState.SECURE,
        GoalFeasibilityState.FEASIBLE,
    }
)
_AT_RISK_STATES = frozenset(
    {
        GoalFeasibilityState.STRETCH,
        GoalFeasibilityState.UNLIKELY,
        GoalFeasibilityState.OVERDUE,
    }
)


class GoalPlanRepository:
    """Create and read plan records only through an authenticated owner."""

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        snapshot: GoalPlanningSnapshot,
        plan: GoalOptimizationPlan,
        occurred_at: datetime,
        predecessor_plan_id: UUID | None = None,
    ) -> GoalPlanRun:
        _validate_write(snapshot=snapshot, plan=plan, occurred_at=occurred_at)
        run_id = uuid4()
        outcome_models = _outcomes(
            run_id=run_id,
            user_id=user_id,
            snapshot=snapshot,
            plan=plan,
        )
        outcomes_by_goal = {item.goal_id: item for item in outcome_models}
        period_models = _periods(
            run_id=run_id,
            user_id=user_id,
            plan=plan,
            outcomes_by_goal=outcomes_by_goal,
        )
        assessments = plan.analysis.assessments
        feasible_count = sum(
            item.feasibility_state in _FEASIBLE_STATES for item in assessments
        )
        at_risk_count = sum(
            item.feasibility_state in _AT_RISK_STATES for item in assessments
        )
        uncertain_count = len(assessments) - feasible_count - at_risk_count
        candidate = plan.optimizer_candidate
        solver = candidate.solver if candidate is not None else None
        schedule_periods = plan.schedule.periods
        run = GoalPlanRun(
            id=run_id,
            user_id=user_id,
            predecessor_plan_id=predecessor_plan_id,
            forecast_run_id=snapshot.provenance.forecast_run_id,
            deterministic_plan_id=plan.plan_id,
            snapshot_id=snapshot.snapshot_id,
            currency=snapshot.currency,
            planning_cutoff_at=snapshot.cutoff_at,
            local_date=snapshot.local_date,
            timezone=snapshot.timezone,
            horizon_start=(
                min(item.period_start for item in schedule_periods)
                if schedule_periods
                else None
            ),
            horizon_end=(
                max(item.period_start for item in schedule_periods)
                if schedule_periods
                else None
            ),
            contract_version=snapshot.contract_version,
            plan_policy_version=plan.policy_version,
            capacity_policy_version=(
                snapshot.savings_capacity.policy_version
                if snapshot.savings_capacity is not None
                else None
            ),
            feasibility_policy_version=plan.analysis.feasibility_policy_version,
            ranking_policy_version=plan.analysis.ranking.policy_version,
            greedy_policy_version=plan.analysis.greedy_baseline.policy_version,
            optimization_policy_version=CONSTRAINED_OPTIMIZATION_POLICY_VERSION,
            guardrail_policy_version=plan.guardrails.policy_version,
            strategy=plan.schedule.strategy.value,
            optimizer_status=(
                candidate.status.value if candidate is not None else None
            ),
            overall_feasibility=_overall_feasibility(
                plan=plan,
                goal_count=len(snapshot.goals),
                at_risk_count=at_risk_count,
                uncertain_count=uncertain_count,
            ),
            solver_name=solver.solver_name if solver is not None else None,
            solver_version=solver.solver_version if solver is not None else None,
            allocation_band=plan.schedule.allocation_band,
            forecast_reliability=(
                snapshot.savings_capacity.reliability
                if snapshot.savings_capacity is not None
                else "unavailable"
            ),
            emergency_reserve_amount=money(
                plan.guardrails.emergency_reserve_amount
            ),
            available_savings=money(plan.schedule.capacity_total),
            allocated_savings=money(plan.schedule.allocated_total),
            unallocated_savings=money(plan.schedule.unallocated_total),
            weighted_funding_score=plan.schedule.weighted_funding_score,
            greedy_weighted_funding_score=(
                plan.comparison.greedy_baseline_weighted_funding_score
            ),
            guarded_fallback_weighted_funding_score=(
                plan.comparison.guarded_fallback_weighted_funding_score
            ),
            optimized_weighted_funding_score=(
                plan.comparison.optimized_weighted_funding_score
            ),
            selected_score_delta_from_greedy=(
                plan.comparison.selected_score_delta_from_greedy
            ),
            goal_count=len(snapshot.goals),
            feasible_goal_count=feasible_count,
            at_risk_goal_count=at_risk_count,
            uncertain_goal_count=uncertain_count,
            fully_funded_goal_count=plan.schedule.fully_funded_goal_count,
            deadline_met_goal_count=plan.schedule.deadline_met_goal_count,
            assumptions=[item.value for item in plan.assumptions],
            reason_codes=[item.value for item in plan.reason_codes],
            snapshot_warnings=[item.value for item in snapshot.warnings],
            guardrail_reason_codes=[
                item.value for item in plan.guardrails.reason_codes
            ],
            outcomes=outcome_models,
            periods=period_models,
            events=[
                GoalPlanEvent(
                    user_id=user_id,
                    plan_run_id=run_id,
                    previous_status=None,
                    status=GoalPlanStatus.GENERATED.value,
                    source=GoalPlanEventSource.SYSTEM,
                    occurred_at=occurred_at,
                    successor_plan_id=None,
                    reason_code="plan_generated",
                )
            ],
        )
        session.add(run)
        await session.flush()
        return run

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        plan_id: UUID,
        for_update: bool = False,
    ) -> GoalPlanRun | None:
        statement = (
            select(GoalPlanRun)
            .options(*_load_options())
            .where(GoalPlanRun.user_id == user_id, GoalPlanRun.id == plan_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[GoalPlanRun, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= MAX_GOAL_PLAN_HISTORY:
            raise ValueError("Goal-plan history limit must be between 1 and 100.")
        rows = await session.scalars(
            select(GoalPlanRun)
            .options(*_load_options())
            .where(GoalPlanRun.user_id == user_id)
            .order_by(GoalPlanRun.created_at.desc(), GoalPlanRun.id.desc())
            .limit(limit)
        )
        return tuple(rows.all())

    async def transition(
        self,
        session: AsyncSession,
        *,
        run: GoalPlanRun,
        user_id: UUID,
        expected_status: GoalPlanStatus,
        new_status: GoalPlanStatus,
        source: GoalPlanEventSource,
        occurred_at: datetime,
        successor_plan_id: UUID | None = None,
        reason_code: str,
    ) -> GoalPlanRun:
        if run.user_id != user_id:
            raise ValueError("Goal-plan lifecycle writes require the trusted owner.")
        if run.status is not expected_status:
            raise ValueError("Goal-plan lifecycle state changed before transition.")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("Goal-plan event timestamps must be timezone-aware.")
        if run.events and occurred_at < run.events[-1].occurred_at:
            raise ValueError("Goal-plan lifecycle timestamps must be chronological.")
        _validate_transition(
            previous=expected_status,
            new=new_status,
            source=source,
            successor_plan_id=successor_plan_id,
            occurred_at=occurred_at,
            reason_code=reason_code,
        )
        run.events.append(
            GoalPlanEvent(
                user_id=user_id,
                plan_run_id=run.id,
                previous_status=expected_status.value,
                status=new_status.value,
                source=source,
                occurred_at=occurred_at,
                successor_plan_id=successor_plan_id,
                reason_code=reason_code,
            )
        )
        await session.flush()
        return run


def _load_options() -> tuple[object, ...]:
    return (
        selectinload(GoalPlanRun.outcomes),
        selectinload(GoalPlanRun.periods).selectinload(
            GoalPlanPeriod.allocations
        ),
        selectinload(GoalPlanRun.events),
    )


def _validate_write(
    *,
    snapshot: GoalPlanningSnapshot,
    plan: GoalOptimizationPlan,
    occurred_at: datetime,
) -> None:
    if plan.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Goal plan and planning snapshot identifiers must match.")
    if plan.schedule.currency != snapshot.currency:
        raise ValueError("Goal plan and planning snapshot currencies must match.")
    _validate_schedule(snapshot=snapshot, plan=plan)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("Goal-plan event timestamps must be timezone-aware.")
    if occurred_at < snapshot.cutoff_at:
        raise ValueError("Goal-plan generation cannot precede its evidence cutoff.")
    if len({item.goal_id for item in snapshot.goals}) != len(snapshot.goals):
        raise ValueError("Goal-plan persistence requires unique snapshot goals.")


def _validate_schedule(
    *,
    snapshot: GoalPlanningSnapshot,
    plan: GoalOptimizationPlan,
) -> None:
    schedule = plan.schedule
    verified = verify_allocation_invariants(
        snapshot=snapshot,
        ranking=plan.analysis.ranking,
        periods=schedule.periods,
        emergency_reserve_amount=plan.guardrails.emergency_reserve_amount,
    )
    if not verified.valid or verified != schedule.invariants:
        raise ValueError("Goal-plan persistence requires verified safe allocations.")
    projections = build_allocation_projections(
        snapshot=snapshot,
        ranking=plan.analysis.ranking,
        periods=schedule.periods,
    )
    if projections != schedule.goal_projections:
        raise ValueError("Goal-plan projections must reconcile with allocations.")
    capacity_total = money(
        sum((item.available_capacity for item in schedule.periods), Decimal("0"))
    )
    allocated_total = money(
        sum((item.allocated_amount for item in schedule.periods), Decimal("0"))
    )
    unallocated_total = money(
        sum((item.unallocated_amount for item in schedule.periods), Decimal("0"))
    )
    if (
        schedule.capacity_total != capacity_total
        or schedule.allocated_total != allocated_total
        or schedule.unallocated_total != unallocated_total
    ):
        raise ValueError("Goal-plan aggregate totals must reconcile exactly.")
    expected_score = calculate_weighted_funding_score(
        ranking=plan.analysis.ranking,
        projections=projections,
    )
    eligible_projections = tuple(
        item for item in projections if item.starting_remaining_amount > 0
    )
    fully_funded = sum(
        item.projected_remaining_amount == 0 for item in eligible_projections
    )
    deadline_met = sum(item.deadline_met for item in eligible_projections)
    selected_delta = (
        expected_score - plan.comparison.greedy_baseline_weighted_funding_score
    ).quantize(Decimal("0.0001"))
    if (
        schedule.weighted_funding_score != expected_score
        or schedule.fully_funded_goal_count != fully_funded
        or schedule.deadline_met_goal_count != deadline_met
        or plan.comparison.selected_weighted_funding_score != expected_score
        or plan.comparison.selected_allocated_total != allocated_total
        or plan.comparison.selected_score_delta_from_greedy != selected_delta
    ):
        raise ValueError("Goal-plan selected metrics must reconcile exactly.")


def _validate_transition(
    *,
    previous: GoalPlanStatus,
    new: GoalPlanStatus,
    source: GoalPlanEventSource,
    successor_plan_id: UUID | None,
    occurred_at: datetime,
    reason_code: str,
) -> None:
    allowed = {
        GoalPlanStatus.GENERATED: {
            GoalPlanStatus.APPROVED,
            GoalPlanStatus.REJECTED,
            GoalPlanStatus.SUPERSEDED,
        },
        GoalPlanStatus.APPROVED: {GoalPlanStatus.SUPERSEDED},
    }
    if new not in allowed.get(previous, set()):
        raise ValueError("The requested goal-plan lifecycle transition is invalid.")
    expected_source = (
        GoalPlanEventSource.SYSTEM
        if new is GoalPlanStatus.SUPERSEDED
        else GoalPlanEventSource.USER
    )
    if source is not expected_source:
        raise ValueError("Goal-plan lifecycle event source is invalid.")
    if (new is GoalPlanStatus.SUPERSEDED) is (successor_plan_id is None):
        raise ValueError("Goal-plan supersession requires exactly one successor.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("Goal-plan event timestamps must be timezone-aware.")
    if not reason_code.strip() or len(reason_code) > 64:
        raise ValueError("Goal-plan event reason code is invalid.")


def _outcomes(
    *,
    run_id: UUID,
    user_id: UUID,
    snapshot: GoalPlanningSnapshot,
    plan: GoalOptimizationPlan,
) -> list[GoalPlanOutcome]:
    goals = {item.goal_id: item for item in snapshot.goals}
    assessments = {item.goal_id: item for item in plan.analysis.assessments}
    rankings = {item.goal_id: item for item in plan.analysis.ranking.items}
    projections = {item.goal_id: item for item in plan.schedule.goal_projections}
    if not (
        set(goals) == set(assessments) == set(rankings) == set(projections)
    ):
        raise ValueError("Goal-plan outcomes must cover every snapshot goal once.")
    return [
        GoalPlanOutcome(
            id=uuid4(),
            user_id=user_id,
            plan_run_id=run_id,
            goal_id=goal_id,
            goal_name=goals[goal_id].goal_name,
            goal_type=goals[goal_id].goal_type.value,
            priority=goals[goal_id].priority.value,
            target_date=goals[goal_id].target_date,
            rank=rankings[goal_id].rank,
            target_amount=money(goals[goal_id].target_amount),
            current_amount=money(goals[goal_id].current_amount),
            starting_remaining_amount=money(
                projections[goal_id].starting_remaining_amount
            ),
            allocated_amount=money(projections[goal_id].allocated_amount),
            projected_remaining_amount=money(
                projections[goal_id].projected_remaining_amount
            ),
            protected_shortfall=money(
                assessments[goal_id].protected_shortfall
            ),
            expected_shortfall=money(assessments[goal_id].expected_shortfall),
            expected_completion_period=(
                assessments[goal_id].completion_window.expected_period
            ),
            projected_completion_period=(
                projections[goal_id].projected_completion_period
            ),
            deadline_met=projections[goal_id].deadline_met,
            feasibility_state=assessments[goal_id].feasibility_state.value,
            deadline_risk=assessments[goal_id].deadline_risk.value,
            completion_probability=assessments[goal_id].completion_probability,
            evidence_reliability=(
                assessments[goal_id].evidence_reliability.value
            ),
            feasibility_reason_codes=[
                item.value for item in assessments[goal_id].reason_codes
            ],
            ranking_reason_codes=[
                item.value for item in rankings[goal_id].reason_codes
            ],
        )
        for goal_id in (
            item.goal_id
            for item in sorted(
                plan.analysis.ranking.items,
                key=lambda item: item.rank,
            )
        )
    ]


def _periods(
    *,
    run_id: UUID,
    user_id: UUID,
    plan: GoalOptimizationPlan,
    outcomes_by_goal: dict[UUID, GoalPlanOutcome],
) -> list[GoalPlanPeriod]:
    cumulative = {goal_id: Decimal("0.0000") for goal_id in outcomes_by_goal}
    result: list[GoalPlanPeriod] = []
    for source in sorted(plan.schedule.periods, key=lambda item: item.period_start):
        period_id = uuid4()
        allocations: list[GoalPlanAllocation] = []
        for item in sorted(source.allocations, key=lambda allocation: allocation.rank):
            outcome = outcomes_by_goal.get(item.goal_id)
            if outcome is None:
                raise ValueError("Goal-plan allocation references an unknown outcome.")
            cumulative[item.goal_id] = money(
                cumulative[item.goal_id] + item.amount
            )
            allocations.append(
                GoalPlanAllocation(
                    id=uuid4(),
                    user_id=user_id,
                    plan_run_id=run_id,
                    period_id=period_id,
                    outcome_id=outcome.id,
                    goal_id=item.goal_id,
                    rank=item.rank,
                    amount=money(item.amount),
                    cumulative_amount=cumulative[item.goal_id],
                    projected_remaining_amount=money(
                        max(
                            Decimal("0"),
                            outcome.starting_remaining_amount
                            - cumulative[item.goal_id],
                        )
                    ),
                )
            )
        result.append(
            GoalPlanPeriod(
                id=period_id,
                user_id=user_id,
                plan_run_id=run_id,
                period_start=source.period_start,
                available_capacity=money(source.available_capacity),
                allocated_amount=money(source.allocated_amount),
                unallocated_amount=money(source.unallocated_amount),
                allocations=allocations,
            )
        )
    return result


def _overall_feasibility(
    *,
    plan: GoalOptimizationPlan,
    goal_count: int,
    at_risk_count: int,
    uncertain_count: int,
) -> str:
    if goal_count == 0:
        return "unavailable"
    if plan.schedule.strategy.value == "blocked":
        return "blocked"
    if all(
        item.projected_remaining_amount == 0
        for item in plan.schedule.goal_projections
    ):
        return "fully_funded"
    if at_risk_count:
        return "at_risk"
    if uncertain_count:
        return "uncertain"
    return "feasible"
