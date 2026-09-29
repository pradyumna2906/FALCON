"""Immutable, owner-scoped goal-plan persistence tests."""

import asyncio
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.goal_planning import GoalPlanRepository
from falcon_api.models.enums import GoalPlanEventSource, GoalPlanStatus
from goal_plan_test_data import NOW, OWNER_ID, goal_plan_case


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    return session


def _create(*, session=None, owner=OWNER_ID, predecessor=None):
    snapshot, plan = goal_plan_case(user_id=owner)
    resolved_session = session or _session()
    run = asyncio.run(
        GoalPlanRepository().create(
            resolved_session,
            user_id=owner,
            snapshot=snapshot,
            plan=plan,
            occurred_at=NOW,
            predecessor_plan_id=predecessor,
        )
    )
    return run, snapshot, plan, resolved_session


def test_create_freezes_complete_plan_graph_and_provenance() -> None:
    predecessor = uuid4()
    run, snapshot, plan, session = _create(predecessor=predecessor)

    assert run.user_id == OWNER_ID
    assert run.predecessor_plan_id == predecessor
    assert run.deterministic_plan_id == plan.plan_id
    assert run.snapshot_id == snapshot.snapshot_id
    assert run.forecast_run_id == snapshot.provenance.forecast_run_id
    assert run.planning_cutoff_at == snapshot.cutoff_at
    assert run.horizon_start == snapshot.savings_capacity.points[0].period_start
    assert run.horizon_end == snapshot.savings_capacity.points[-1].period_start
    assert run.available_savings == plan.schedule.capacity_total
    assert run.allocated_savings == plan.schedule.allocated_total
    assert run.unallocated_savings == plan.schedule.unallocated_total
    assert run.goal_count == len(run.outcomes) == 1
    assert (
        run.feasible_goal_count
        + run.at_risk_goal_count
        + run.uncertain_goal_count
        == 1
    )
    assert len(run.periods) == 2
    assert sum(len(period.allocations) for period in run.periods) == 2
    assert run.outcomes[0].goal_id == run.periods[0].allocations[0].goal_id
    assert run.periods[-1].allocations[0].cumulative_amount == run.allocated_savings
    assert run.status is GoalPlanStatus.GENERATED
    assert run.decided_at is None
    assert run.events[0].source is GoalPlanEventSource.SYSTEM
    assert run.events[0].reason_code == "plan_generated"
    assert not hasattr(run, "liquid_balance")
    assert not hasattr(run, "outstanding_debt")
    session.add.assert_called_once_with(run)
    session.flush.assert_awaited_once_with()


def test_create_persists_safe_blocked_plan_without_forecast() -> None:
    snapshot, plan = goal_plan_case(with_capacity=False)
    session = _session()

    run = asyncio.run(
        GoalPlanRepository().create(
            session,
            user_id=OWNER_ID,
            snapshot=snapshot,
            plan=plan,
            occurred_at=NOW,
        )
    )

    assert run.forecast_run_id is None
    assert run.horizon_start is None
    assert run.horizon_end is None
    assert run.strategy == "blocked"
    assert run.overall_feasibility == "blocked"
    assert run.periods == []
    assert run.available_savings == 0


@pytest.mark.parametrize(
    ("snapshot_change", "plan_change", "occurred_at", "message"),
    [
        ({"snapshot_id": "d" * 64}, {}, NOW, "identifiers"),
        ({"currency": "USD"}, {}, NOW, "currencies"),
        ({}, {}, datetime(2026, 9, 15, 12), "timezone-aware"),
        ({}, {}, datetime(2026, 9, 15, 11, tzinfo=NOW.tzinfo), "precede"),
    ],
)
def test_create_rejects_mismatched_or_untrusted_evidence(
    snapshot_change,
    plan_change,
    occurred_at,
    message,
) -> None:
    snapshot, plan = goal_plan_case()
    snapshot = replace(snapshot, **snapshot_change)
    plan = replace(plan, **plan_change)

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            GoalPlanRepository().create(
                _session(),
                user_id=OWNER_ID,
                snapshot=snapshot,
                plan=plan,
                occurred_at=occurred_at,
            )
        )


def test_create_rejects_unverified_schedule() -> None:
    snapshot, plan = goal_plan_case()
    unsafe_schedule = replace(
        plan.schedule,
        invariants=replace(plan.schedule.invariants, valid=False),
    )

    with pytest.raises(ValueError, match="verified safe"):
        asyncio.run(
            GoalPlanRepository().create(
                _session(),
                user_id=OWNER_ID,
                snapshot=snapshot,
                plan=replace(plan, schedule=unsafe_schedule),
                occurred_at=NOW,
            )
        )


def test_get_and_list_queries_are_owner_scoped_bounded_and_ordered() -> None:
    repository = GoalPlanRepository()
    session = _session()
    plan_id = uuid4()
    session.scalar.return_value = None

    assert asyncio.run(
        repository.get(
            session,
            user_id=OWNER_ID,
            plan_id=plan_id,
            for_update=True,
        )
    ) is None
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "goal_plan_runs.user_id =" in sql
    assert "goal_plan_runs.id =" in sql
    assert "FOR UPDATE" in sql
    assert OWNER_ID in compiled.params.values()
    assert plan_id in compiled.params.values()

    session.scalar.reset_mock()
    assert asyncio.run(
        repository.get(
            session,
            user_id=OWNER_ID,
            plan_id=plan_id,
        )
    ) is None
    unlocked = str(
        session.scalar.await_args.args[0].compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE" not in unlocked

    scalars = Mock()
    scalars.all.return_value = []
    session.scalars.return_value = scalars
    assert asyncio.run(
        repository.list_recent(session, user_id=OWNER_ID, limit=20)
    ) == ()
    list_statement = session.scalars.await_args.args[0]
    list_sql = str(list_statement.compile(dialect=postgresql.dialect()))
    assert "goal_plan_runs.user_id =" in list_sql
    assert "goal_plan_runs.created_at DESC" in list_sql
    assert "LIMIT" in list_sql

    for invalid in (True, 0, 101):
        with pytest.raises(ValueError, match="between 1 and 100"):
            asyncio.run(
                repository.list_recent(
                    session,
                    user_id=OWNER_ID,
                    limit=invalid,
                )
            )


def test_transition_appends_approval_without_mutating_plan_values() -> None:
    run, _, _, session = _create()
    deterministic_id = run.deterministic_plan_id
    decided_at = NOW.replace(minute=1)

    result = asyncio.run(
        GoalPlanRepository().transition(
            session,
            run=run,
            user_id=OWNER_ID,
            expected_status=GoalPlanStatus.GENERATED,
            new_status=GoalPlanStatus.APPROVED,
            source=GoalPlanEventSource.USER,
            occurred_at=decided_at,
            reason_code="user_approved_plan",
        )
    )

    assert result is run
    assert run.status is GoalPlanStatus.APPROVED
    assert run.decided_at == decided_at
    assert run.deterministic_plan_id == deterministic_id
    assert len(run.events) == 2
    assert run.events[-1].previous_status == "generated"
    assert run.events[-1].successor_plan_id is None
    assert session.flush.await_count == 2


def test_transition_records_auditable_supersession() -> None:
    run, _, _, session = _create()
    successor = uuid4()

    asyncio.run(
        GoalPlanRepository().transition(
            session,
            run=run,
            user_id=OWNER_ID,
            expected_status=GoalPlanStatus.GENERATED,
            new_status=GoalPlanStatus.SUPERSEDED,
            source=GoalPlanEventSource.SYSTEM,
            occurred_at=NOW,
            successor_plan_id=successor,
            reason_code="plan_regenerated",
        )
    )

    assert run.status is GoalPlanStatus.SUPERSEDED
    assert run.successor_plan_id == successor


def test_transition_rejects_non_chronological_and_terminal_changes() -> None:
    run, _, _, session = _create()
    with pytest.raises(ValueError, match="chronological"):
        asyncio.run(
            GoalPlanRepository().transition(
                session,
                run=run,
                user_id=OWNER_ID,
                expected_status=GoalPlanStatus.GENERATED,
                new_status=GoalPlanStatus.APPROVED,
                source=GoalPlanEventSource.USER,
                occurred_at=NOW.replace(hour=11),
                reason_code="approved",
            )
        )

    asyncio.run(
        GoalPlanRepository().transition(
            session,
            run=run,
            user_id=OWNER_ID,
            expected_status=GoalPlanStatus.GENERATED,
            new_status=GoalPlanStatus.REJECTED,
            source=GoalPlanEventSource.USER,
            occurred_at=NOW,
            reason_code="rejected",
        )
    )
    with pytest.raises(ValueError, match="transition is invalid"):
        asyncio.run(
            GoalPlanRepository().transition(
                session,
                run=run,
                user_id=OWNER_ID,
                expected_status=GoalPlanStatus.REJECTED,
                new_status=GoalPlanStatus.APPROVED,
                source=GoalPlanEventSource.USER,
                occurred_at=NOW,
                reason_code="approved",
            )
        )


def test_create_rejects_duplicate_or_incomplete_goal_coverage() -> None:
    snapshot, plan = goal_plan_case()

    with pytest.raises(ValueError, match="unique snapshot goals"):
        asyncio.run(
            GoalPlanRepository().create(
                _session(),
                user_id=OWNER_ID,
                snapshot=replace(snapshot, goals=snapshot.goals * 2),
                plan=plan,
                occurred_at=NOW,
            )
        )

    incomplete_analysis = replace(plan.analysis, assessments=())
    with pytest.raises(ValueError, match="cover every snapshot goal"):
        asyncio.run(
            GoalPlanRepository().create(
                _session(),
                user_id=OWNER_ID,
                snapshot=snapshot,
                plan=replace(plan, analysis=incomplete_analysis),
                occurred_at=NOW,
            )
        )


@pytest.mark.parametrize(
    "mismatch",
    ["totals", "projections", "comparison", "delta"],
)
def test_create_recomputes_and_rejects_tampered_plan_metrics(mismatch) -> None:
    snapshot, plan = goal_plan_case()
    if mismatch == "totals":
        plan = replace(
            plan,
            schedule=replace(
                plan.schedule,
                capacity_total=plan.schedule.capacity_total + 1,
            ),
        )
        message = "aggregate totals"
    elif mismatch == "projections":
        projection = replace(
            plan.schedule.goal_projections[0],
            allocated_amount=plan.schedule.goal_projections[0].allocated_amount - 1,
        )
        plan = replace(
            plan,
            schedule=replace(plan.schedule, goal_projections=(projection,)),
        )
        message = "projections"
    elif mismatch == "comparison":
        plan = replace(
            plan,
            comparison=replace(
                plan.comparison,
                selected_allocated_total=(
                    plan.comparison.selected_allocated_total - 1
                ),
            ),
        )
        message = "selected metrics"
    else:
        plan = replace(
            plan,
            comparison=replace(
                plan.comparison,
                selected_score_delta_from_greedy=Decimal("1.0000"),
            ),
        )
        message = "selected metrics"

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            GoalPlanRepository().create(
                _session(),
                user_id=OWNER_ID,
                snapshot=snapshot,
                plan=plan,
                occurred_at=NOW,
            )
        )


@pytest.mark.parametrize(
    ("owner", "expected", "new", "source", "successor", "occurred", "reason"),
    [
        (
            uuid4(),
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.APPROVED,
            GoalPlanEventSource.USER,
            None,
            NOW,
            "approved",
        ),
        (
            OWNER_ID,
            GoalPlanStatus.APPROVED,
            GoalPlanStatus.SUPERSEDED,
            GoalPlanEventSource.SYSTEM,
            uuid4(),
            NOW,
            "regenerated",
        ),
        (
            OWNER_ID,
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.REJECTED,
            GoalPlanEventSource.SYSTEM,
            None,
            NOW,
            "rejected",
        ),
        (
            OWNER_ID,
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.SUPERSEDED,
            GoalPlanEventSource.SYSTEM,
            None,
            NOW,
            "regenerated",
        ),
        (
            OWNER_ID,
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.APPROVED,
            GoalPlanEventSource.USER,
            uuid4(),
            NOW,
            "approved",
        ),
        (
            OWNER_ID,
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.APPROVED,
            GoalPlanEventSource.USER,
            None,
            datetime(2026, 9, 15, 12),
            "approved",
        ),
        (
            OWNER_ID,
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.APPROVED,
            GoalPlanEventSource.USER,
            None,
            NOW,
            " ",
        ),
        (
            OWNER_ID,
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.APPROVED,
            GoalPlanEventSource.USER,
            None,
            NOW,
            "x" * 65,
        ),
    ],
)
def test_invalid_lifecycle_writes_fail_closed(
    owner,
    expected,
    new,
    source,
    successor,
    occurred,
    reason,
) -> None:
    run, _, _, session = _create()

    with pytest.raises(ValueError):
        asyncio.run(
            GoalPlanRepository().transition(
                session,
                run=run,
                user_id=owner,
                expected_status=expected,
                new_status=new,
                source=source,
                occurred_at=occurred,
                successor_plan_id=successor,
                reason_code=reason,
            )
        )
