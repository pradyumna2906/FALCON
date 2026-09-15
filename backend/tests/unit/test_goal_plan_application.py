"""Transactional final-Phase-10 goal-plan orchestration tests."""

import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning import (
    GoalPlanGenerationCommand,
    GoalPlanMonitor,
    GoalPlanOperation,
    GoalPlanRepository,
    GoalPlanningSnapshotService,
    MultiGoalOptimizationService,
)
from falcon_api.models.enums import GoalPlanEventSource, GoalPlanStatus
from falcon_api.models.goal_plan import GoalPlanEvent, GoalPlanRun
from goal_plan_test_data import (
    NOW,
    OWNER_ID,
    ZeroSolver,
    goal_plan_case,
    transient_goal_plan_run,
)


class FixedClock:
    def now(self):
        return NOW


def _dependencies(*, with_capacity: bool = True):
    snapshot, _ = goal_plan_case(with_capacity=with_capacity)
    run = transient_goal_plan_run(with_capacity=with_capacity)
    snapshots = AsyncMock(spec=GoalPlanningSnapshotService)
    snapshots.build.return_value = snapshot
    repository = AsyncMock(spec=GoalPlanRepository)
    repository.create.return_value = run
    repository.get.return_value = run
    repository.list_recent.return_value = (run,)
    monitor = Mock(spec=GoalPlanMonitor)
    monitor.start.return_value = 10.0
    service = MultiGoalOptimizationService(
        snapshot_service=snapshots,
        repository=repository,
        solver=ZeroSolver(),
        monitor=monitor,
        clock=FixedClock(),
    )
    return service, snapshots, repository, monitor, run


def _command() -> GoalPlanGenerationCommand:
    return GoalPlanGenerationCommand(
        currency="INR",
        trusted_timezone="Asia/Kolkata",
    )


def _mark(run: GoalPlanRun, status: GoalPlanStatus) -> None:
    run.events.append(
        GoalPlanEvent(
            user_id=run.user_id,
            plan_run_id=run.id,
            previous_status=GoalPlanStatus.GENERATED.value,
            status=status.value,
            source=GoalPlanEventSource.USER,
            occurred_at=NOW,
            successor_plan_id=None,
            reason_code=f"user_{status.value}_plan",
        )
    )


def test_generate_freezes_trusted_snapshot_optimizes_and_persists_once() -> None:
    service, snapshots, repository, monitor, run = _dependencies()
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.generate(session, user_id=OWNER_ID, command=_command())
    )

    assert result is run
    snapshots.build.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        currency="INR",
        trusted_timezone="Asia/Kolkata",
    )
    repository.create.assert_awaited_once()
    persisted = repository.create.await_args.kwargs
    assert repository.create.await_args.args == (session,)
    assert persisted["user_id"] == OWNER_ID
    assert persisted["snapshot"].snapshot_id == run.snapshot_id
    assert persisted["plan"].schedule.invariants.valid is True
    assert persisted["occurred_at"] == NOW
    assert persisted["predecessor_plan_id"] is None
    monitor.record_generation.assert_called_once_with(
        run,
        operation=GoalPlanOperation.GENERATE,
        started_at=10.0,
    )


@pytest.mark.parametrize("failure_source", ["snapshot", "persistence"])
def test_generate_maps_invalid_evidence_or_persistence_to_safe_error(
    failure_source,
) -> None:
    service, snapshots, repository, _, _ = _dependencies()
    if failure_source == "snapshot":
        snapshots.build.side_effect = ValueError("unsafe snapshot")
    else:
        repository.create.side_effect = ValueError("unsafe persistence")

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.generate(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                command=_command(),
            )
        )

    assert captured.value.code == "goal_plan_unavailable"
    assert captured.value.status_code == 422


def test_get_and_list_delegate_owner_scope() -> None:
    service, _, repository, _, run = _dependencies()
    session = AsyncMock(spec=AsyncSession)

    assert asyncio.run(
        service.get(session, user_id=OWNER_ID, plan_id=run.id)
    ) is run
    assert asyncio.run(
        service.list_recent(session, user_id=OWNER_ID, limit=25)
    ) == (run,)
    repository.get.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        plan_id=run.id,
        for_update=False,
    )
    repository.list_recent.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        limit=25,
    )


def test_foreign_or_missing_plan_uses_indistinguishable_not_found_error() -> None:
    service, _, repository, _, _ = _dependencies()
    repository.get.return_value = None

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.get(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                plan_id=uuid4(),
            )
        )

    assert captured.value.code == "goal_plan_not_found"
    assert captured.value.status_code == 404


def test_approve_appends_user_decision_without_moving_money() -> None:
    service, _, repository, monitor, run = _dependencies()
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.approve(session, user_id=OWNER_ID, plan_id=run.id)
    )

    assert result is run
    repository.get.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        plan_id=run.id,
        for_update=True,
    )
    repository.transition.assert_awaited_once()
    transition = repository.transition.await_args.kwargs
    assert transition["expected_status"] is GoalPlanStatus.GENERATED
    assert transition["new_status"] is GoalPlanStatus.APPROVED
    assert transition["occurred_at"] == NOW
    assert transition["successor_plan_id"] is None
    assert transition["reason_code"] == "user_approved_plan"
    assert not hasattr(service, "contribution_service")
    monitor.record_transition.assert_called_once()


def test_blocked_plan_cannot_be_approved() -> None:
    service, _, repository, monitor, run = _dependencies(with_capacity=False)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.approve(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                plan_id=run.id,
            )
        )

    assert captured.value.code == "goal_plan_not_approvable"
    assert captured.value.status_code == 409
    repository.transition.assert_not_awaited()
    monitor.record_transition.assert_not_called()


@pytest.mark.parametrize("operation", ["approve", "reject"])
def test_decision_rejects_stale_or_terminal_state(operation) -> None:
    service, _, repository, _, run = _dependencies()
    _mark(run, GoalPlanStatus.APPROVED)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            getattr(service, operation)(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                plan_id=run.id,
            )
        )

    assert captured.value.code == "goal_plan_transition_conflict"
    assert captured.value.status_code == 409
    repository.transition.assert_not_awaited()


@pytest.mark.parametrize("operation", ["approve", "reject"])
def test_repository_transition_race_is_mapped_to_conflict(operation) -> None:
    service, _, repository, _, run = _dependencies()
    repository.transition.side_effect = ValueError("stale")

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            getattr(service, operation)(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                plan_id=run.id,
            )
        )

    assert captured.value.code == "goal_plan_transition_conflict"


def test_reject_appends_user_rejection_and_records_bounded_telemetry() -> None:
    service, _, repository, monitor, run = _dependencies()

    assert asyncio.run(
        service.reject(
            AsyncMock(spec=AsyncSession),
            user_id=OWNER_ID,
            plan_id=run.id,
        )
    ) is run

    transition = repository.transition.await_args.kwargs
    assert transition["new_status"] is GoalPlanStatus.REJECTED
    assert transition["reason_code"] == "user_rejected_plan"
    monitor.record_transition.assert_called_once_with(
        operation=GoalPlanOperation.REJECT,
        status=GoalPlanStatus.REJECTED,
        started_at=10.0,
    )


@pytest.mark.parametrize(
    "previous_status",
    [GoalPlanStatus.GENERATED, GoalPlanStatus.APPROVED],
)
def test_regenerate_creates_new_version_then_supersedes_previous(
    previous_status,
) -> None:
    service, snapshots, repository, monitor, previous = _dependencies()
    if previous_status is GoalPlanStatus.APPROVED:
        _mark(previous, GoalPlanStatus.APPROVED)
    successor = transient_goal_plan_run()
    repository.create.return_value = successor
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.regenerate(
            session,
            user_id=OWNER_ID,
            plan_id=previous.id,
            trusted_timezone="Asia/Kolkata",
        )
    )

    assert result is successor
    snapshots.build.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        currency=previous.currency,
        trusted_timezone="Asia/Kolkata",
    )
    assert repository.create.await_args.kwargs["predecessor_plan_id"] == previous.id
    transition = repository.transition.await_args.kwargs
    assert transition["run"] is previous
    assert transition["expected_status"] is previous_status
    assert transition["new_status"] is GoalPlanStatus.SUPERSEDED
    assert transition["successor_plan_id"] == successor.id
    assert transition["reason_code"] == "plan_regenerated"
    monitor.record_generation.assert_called_once_with(
        successor,
        operation=GoalPlanOperation.REGENERATE,
        started_at=10.0,
    )


def test_regenerate_rejects_terminal_plan_and_transition_race() -> None:
    service, _, repository, _, previous = _dependencies()
    _mark(previous, GoalPlanStatus.REJECTED)

    with pytest.raises(ApplicationError, match="lifecycle"):
        asyncio.run(
            service.regenerate(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                plan_id=previous.id,
                trusted_timezone="UTC",
            )
        )
    repository.create.assert_not_awaited()

    service, _, repository, _, previous = _dependencies()
    repository.transition.side_effect = ValueError("stale")
    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.regenerate(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                plan_id=previous.id,
                trusted_timezone="UTC",
            )
        )
    assert captured.value.code == "goal_plan_transition_conflict"
