"""Deterministic goal-plan test data shared across final Phase 10 unit tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.goal_planning import (
    GoalPlanRepository,
    LinearProgramSolution,
    LinearSolverStatus,
    SavingsCapacityPlan,
    SavingsCapacityPoint,
    build_goal_optimization_plan,
    calculate_goal_progress,
)
from falcon_api.goal_planning.plan import GoalOptimizationPlan
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningBudgetEvidence,
    PlanningFinancialEvidence,
    PlanningProfileEvidence,
    PlanningProvenance,
)
from falcon_api.models.enums import (
    GoalPriority,
    GoalStatus,
    GoalType,
    ProfileCompletionStatus,
)
from falcon_api.models.goal_plan import GoalPlanRun
from falcon_api.models.planning import Goal


NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
OWNER_ID = UUID("10000000-0000-4000-8000-000000000001")
GOAL_ID = UUID("20000000-0000-4000-8000-000000000001")
FORECAST_ID = UUID("30000000-0000-4000-8000-000000000001")


class ZeroSolver:
    """Return a valid but dominated schedule so fallback behavior is stable."""

    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del upper_bound_matrix, upper_bounds, bounds
        return LinearProgramSolution(
            status=LinearSolverStatus.OPTIMAL,
            values=tuple(0.0 for _ in objective),
            objective_value=0.0,
            solver_name="zero_test_solver",
            solver_version="1",
            message="valid but dominated",
            iterations=0,
        )


def goal_plan_case(
    *,
    user_id: UUID = OWNER_ID,
    with_capacity: bool = True,
) -> tuple[GoalPlanningSnapshot, GoalOptimizationPlan]:
    """Build one deterministic snapshot and its verified optimization plan."""
    goal = Goal(
        id=GOAL_ID,
        user_id=user_id,
        name="Education Fund",
        goal_type=GoalType.EDUCATION,
        target_amount=Decimal("100.0000"),
        starting_amount=Decimal("0.0000"),
        currency="INR",
        target_date=date(2026, 12, 31),
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
        description=None,
        created_at=NOW,
        updated_at=NOW,
    )
    progress = calculate_goal_progress(
        goal=goal,
        contribution_amount=Decimal("0"),
        calculated_on=date(2026, 9, 15),
    )
    points = tuple(
        SavingsCapacityPoint(
            period_start=period,
            protected_amount=Decimal("50.0000"),
            expected_amount=Decimal("75.0000"),
            upside_amount=Decimal("100.0000"),
        )
        for period in (date(2026, 10, 1), date(2026, 11, 1))
    )
    capacity = (
        SavingsCapacityPlan(
            forecast_run_id=FORECAST_ID,
            currency="INR",
            policy_version="2026.1",
            protection_band="95_percent",
            reliability="normal",
            points=points,
            protected_total=Decimal("100.0000"),
            expected_total=Decimal("150.0000"),
            upside_total=Decimal("200.0000"),
        )
        if with_capacity
        else None
    )
    snapshot = GoalPlanningSnapshot(
        snapshot_id="c" * 64,
        contract_version="2026.1",
        cutoff_at=NOW,
        local_date=date(2026, 9, 15),
        timezone="Asia/Kolkata",
        currency="INR",
        goals=(progress,),
        profile=PlanningProfileEvidence(
            completion_status=ProfileCompletionStatus.COMPLETE,
            income_stability="stable",
            emergency_fund_target_months=Decimal("3"),
            updated_at=NOW,
        ),
        finances=PlanningFinancialEvidence(
            liquid_balance=Decimal("2000.0000"),
            liability_account_count=0,
            liability_payment_count=0,
            outstanding_debt=Decimal("0.0000"),
            monthly_debt_payment=Decimal("0.0000"),
            source_last_updated_at=NOW,
        ),
        budgets=PlanningBudgetEvidence(
            active_budget_count=1,
            budget_with_overall_limit_count=1,
            total_overall_limit=Decimal("500.0000"),
            source_last_updated_at=NOW,
        ),
        savings_capacity=capacity,
        warnings=(),
        provenance=PlanningProvenance(
            goal_ids=(GOAL_ID,),
            contribution_count=0,
            forecast_run_id=FORECAST_ID if with_capacity else None,
            source_last_updated_at=NOW,
        ),
    )
    return snapshot, build_goal_optimization_plan(snapshot, solver=ZeroSolver())


def transient_goal_plan_run(
    *,
    user_id: UUID = OWNER_ID,
    with_capacity: bool = True,
) -> GoalPlanRun:
    """Build the complete ORM graph without opening a database connection."""
    snapshot, plan = goal_plan_case(
        user_id=user_id,
        with_capacity=with_capacity,
    )
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    run = asyncio.run(
        GoalPlanRepository().create(
            session,
            user_id=user_id,
            snapshot=snapshot,
            plan=plan,
            occurred_at=NOW,
        )
    )
    _stamp(run)
    return run


def _stamp(run: GoalPlanRun) -> None:
    """Populate database-generated audit timestamps for response validation."""
    records = [run, *run.outcomes, *run.periods, *run.events]
    records.extend(
        allocation
        for period in run.periods
        for allocation in period.allocations
    )
    for record in records:
        record.created_at = NOW
        record.updated_at = NOW
