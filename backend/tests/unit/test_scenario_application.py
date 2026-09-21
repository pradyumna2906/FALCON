"""Checkpoint 11.12 orchestration, replay, and lifecycle tests."""

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.core.errors import ApplicationError
from falcon_api.models.enums import (
    ScenarioSimulationEventSource,
    ScenarioSimulationEventType,
)
from falcon_api.models.scenario import ScenarioEvent
from falcon_api.scenario_simulation import (
    ScenarioAssumptions,
    ScenarioExecutionBusyError,
    ScenarioExecutionGuard,
    ScenarioFailureReason,
    ScenarioOperation,
    ScenarioRateLimitError,
    ScenarioSelectionCommand,
    ScenarioSimulationCommand,
    ScenarioSimulationMonitor,
    ScenarioSimulationRepository,
    ScenarioSimulationService,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceService
from goal_plan_test_data import GOAL_ID, OWNER_ID
from scenario_test_data import SNAPSHOT_NOW, transient_scenario_run


RUN = transient_scenario_run()
SCENARIO = ScenarioAssumptions(
    name="Lower income",
    income_change_percent=Decimal("-10"),
)


class FixedClock:
    def now(self):
        return SNAPSHOT_NOW


def _service(*, execution_guard=None):
    evidence = AsyncMock(spec=ScenarioEvidenceService)
    repository = AsyncMock(spec=ScenarioSimulationRepository)
    analyzer = Mock(return_value=Mock(name="analysis"))
    monitor = Mock(spec=ScenarioSimulationMonitor)
    monitor.start.return_value = 1.0
    service = ScenarioSimulationService(
        evidence_service=evidence,
        repository=repository,
        analyzer=analyzer,
        monitor=monitor,
        execution_guard=execution_guard,
        clock=FixedClock(),
    )
    return service, evidence, repository, analyzer, monitor


def _command() -> ScenarioSimulationCommand:
    return ScenarioSimulationCommand(
        source_plan_id=RUN.source_plan_id,
        scenarios=(SCENARIO,),
    )


def test_simulate_runs_one_transactional_pipeline_and_persists_result() -> None:
    service, evidence, repository, analyzer, monitor = _service()
    session = AsyncMock(spec=AsyncSession)
    snapshot = Mock(name="snapshot")
    evidence.build.return_value = snapshot
    repository.create.return_value = RUN

    result = asyncio.run(
        service.simulate(session, user_id=OWNER_ID, command=_command())
    )

    assert result is RUN
    evidence.build.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        source_plan_id=RUN.source_plan_id,
        scenarios=(SCENARIO,),
    )
    analyzer.assert_called_once_with(snapshot, config=None, solver=None)
    repository.create.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        snapshot=snapshot,
        analysis=analyzer.return_value,
        occurred_at=SNAPSHOT_NOW,
    )
    monitor.record_simulation.assert_called_once_with(
        RUN,
        operation=ScenarioOperation.SIMULATE,
        started_at=1.0,
    )


def test_regenerate_replays_all_stored_user_assumptions_and_seed() -> None:
    service, evidence, repository, analyzer, monitor = _service()
    session = AsyncMock(spec=AsyncSession)
    custom = next(item for item in RUN.definitions if item.assumptions is not None)
    original = custom.assumptions
    custom.assumptions = {
        "name": "Complete replay",
        "income_change_percent": "-10",
        "expense_change_percent": "5",
        "one_time_expenses": [
            {"period_start": "2026-10-01", "amount": "10"}
        ],
        "recurring_expense_adjustments": [
            {
                "start_period": "2026-10-01",
                "end_period": "2026-11-01",
                "monthly_delta": "2",
            }
        ],
        "debt_payment_adjustments": [
            {
                "start_period": "2026-10-01",
                "end_period": "2026-11-01",
                "monthly_delta": "3",
            }
        ],
        "income_interruptions": [
            {
                "start_period": "2026-11-01",
                "end_period": "2026-11-01",
                "retained_income_percent": "40",
            }
        ],
        "goal_adjustments": [
            {
                "goal_id": str(GOAL_ID),
                "target_amount": "1000",
                "target_date": "2027-03-31",
                "priority": "critical",
                "monthly_contribution_delta": "4",
                "pause_start": "2026-10-01",
                "pause_end": "2026-10-01",
            }
        ],
        "emergency_fund_target_months": "6",
    }
    repository.get.return_value = RUN
    evidence.build.return_value = Mock(name="snapshot")
    repository.create.return_value = RUN
    try:
        result = asyncio.run(
            service.regenerate(session, user_id=OWNER_ID, run_id=RUN.id)
        )
    finally:
        custom.assumptions = original

    assert result is RUN
    scenarios = evidence.build.await_args.kwargs["scenarios"]
    assert len(scenarios) == 1
    assert scenarios[0].name == "Complete replay"
    assert scenarios[0].goal_adjustments[0].priority.value == "critical"
    config = analyzer.call_args.kwargs["config"]
    assert config.trial_count == RUN.trial_count
    assert config.seed == RUN.root_seed
    monitor.record_simulation.assert_called_once_with(
        RUN,
        operation=ScenarioOperation.REGENERATE,
        started_at=1.0,
    )


def test_regenerate_rejects_corrupt_stored_assumptions_without_analysis() -> None:
    service, _, repository, analyzer, _ = _service()
    custom = next(item for item in RUN.definitions if item.assumptions is not None)
    original = custom.assumptions
    custom.assumptions = {"name": "Broken", "one_time_expenses": {}}
    repository.get.return_value = RUN
    try:
        with pytest.raises(ApplicationError) as captured:
            asyncio.run(
                service.regenerate(
                    AsyncMock(spec=AsyncSession),
                    user_id=OWNER_ID,
                    run_id=RUN.id,
                )
            )
    finally:
        custom.assumptions = original

    assert captured.value.status_code == 422
    assert captured.value.code == "scenario_simulation_unavailable"
    analyzer.assert_not_called()


def test_owner_scoped_get_compare_list_and_missing_are_indistinguishable() -> None:
    service, _, repository, _, _ = _service()
    session = AsyncMock(spec=AsyncSession)
    repository.get.return_value = RUN
    repository.list_recent.return_value = (RUN,)

    assert asyncio.run(service.get(session, user_id=OWNER_ID, run_id=RUN.id)) is RUN
    assert (
        asyncio.run(service.compare(session, user_id=OWNER_ID, run_id=RUN.id))
        is RUN
    )
    assert asyncio.run(service.list_recent(session, user_id=OWNER_ID, limit=5)) == (
        RUN,
    )
    repository.get.return_value = None
    with pytest.raises(ApplicationError) as captured:
        asyncio.run(service.get(session, user_id=uuid4(), run_id=RUN.id))
    assert captured.value.status_code == 404
    assert captured.value.code == "scenario_simulation_not_found"


def test_selection_uses_owner_lock_and_compare_and_set() -> None:
    service, _, repository, _, monitor = _service()
    session = AsyncMock(spec=AsyncSession)
    target = RUN.definitions[0].id
    repository.get.return_value = RUN

    result = asyncio.run(
        service.select(
            session,
            user_id=OWNER_ID,
            run_id=RUN.id,
            command=ScenarioSelectionCommand(
                scenario_definition_id=target,
                expected_selected_scenario_id=None,
            ),
        )
    )

    assert result is RUN
    repository.get.assert_awaited_once_with(
        session,
        user_id=OWNER_ID,
        run_id=RUN.id,
        for_update=True,
    )
    repository.select.assert_awaited_once_with(
        session,
        run=RUN,
        user_id=OWNER_ID,
        scenario_definition_id=target,
        occurred_at=SNAPSHOT_NOW,
    )
    monitor.record_selection.assert_called_once_with(
        operation=ScenarioOperation.SELECT,
        started_at=1.0,
    )


def test_selection_rejects_stale_state_and_invalid_repository_transition() -> None:
    service, _, repository, _, monitor = _service()
    repository.get.return_value = RUN
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ApplicationError) as stale:
        asyncio.run(
            service.select(
                session,
                user_id=OWNER_ID,
                run_id=RUN.id,
                command=ScenarioSelectionCommand(
                    scenario_definition_id=RUN.definitions[0].id,
                    expected_selected_scenario_id=uuid4(),
                ),
            )
        )
    assert stale.value.status_code == 409
    repository.select.assert_not_awaited()

    repository.select.side_effect = ValueError("foreign definition")
    with pytest.raises(ApplicationError) as invalid:
        asyncio.run(
            service.select(
                session,
                user_id=OWNER_ID,
                run_id=RUN.id,
                command=ScenarioSelectionCommand(uuid4(), None),
            )
        )
    assert invalid.value.status_code == 409
    assert monitor.record_failure.call_count == 2


def test_selection_can_clear_only_the_expected_active_selection() -> None:
    service, _, repository, _, monitor = _service()
    selected_id = RUN.definitions[0].id
    event = ScenarioEvent(
        user_id=OWNER_ID,
        simulation_run_id=RUN.id,
        scenario_definition_id=selected_id,
        event_type=ScenarioSimulationEventType.SELECTED,
        source=ScenarioSimulationEventSource.USER,
        occurred_at=SNAPSHOT_NOW,
        reason_code="test_selection",
    )
    RUN.events.append(event)
    repository.get.return_value = RUN
    try:
        result = asyncio.run(
            service.select(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                run_id=RUN.id,
                command=ScenarioSelectionCommand(None, selected_id),
            )
        )
    finally:
        RUN.events.pop()

    assert result is RUN
    repository.clear_selection.assert_awaited_once()
    monitor.record_selection.assert_called_once_with(
        operation=ScenarioOperation.CLEAR_SELECTION,
        started_at=1.0,
    )


def test_selection_cannot_clear_when_no_selection_is_active() -> None:
    service, _, repository, _, _ = _service()
    repository.get.return_value = RUN

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.select(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                run_id=RUN.id,
                command=ScenarioSelectionCommand(None, None),
            )
        )

    assert captured.value.status_code == 409
    repository.clear_selection.assert_not_awaited()


@pytest.mark.parametrize(
    ("failure", "code", "reason"),
    [
        (
            ScenarioExecutionBusyError(),
            "scenario_capacity_exhausted",
            ScenarioFailureReason.CAPACITY_EXHAUSTED,
        ),
        (
            ScenarioRateLimitError(),
            "scenario_rate_limited",
            ScenarioFailureReason.RATE_LIMITED,
        ),
    ],
)
def test_capacity_failures_are_safe_429_errors(failure, code, reason) -> None:
    class RejectingGuard:
        @asynccontextmanager
        async def slot(self, *, user_id: UUID):
            del user_id
            raise failure
            yield

    service, _, _, _, monitor = _service(execution_guard=RejectingGuard())
    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.simulate(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                command=_command(),
            )
        )
    assert captured.value.status_code == 429
    assert captured.value.code == code
    monitor.record_failure.assert_called_once_with(
        operation=ScenarioOperation.SIMULATE,
        reason=reason,
        started_at=1.0,
    )


def test_evidence_and_analysis_failures_never_persist_partial_runs() -> None:
    service, evidence, repository, analyzer, monitor = _service()
    session = AsyncMock(spec=AsyncSession)
    evidence.build.side_effect = ApplicationError(
        code="goal_plan_not_found",
        message="The requested source plan was not found.",
        status_code=404,
    )
    with pytest.raises(ApplicationError) as missing:
        asyncio.run(service.simulate(session, user_id=OWNER_ID, command=_command()))
    assert missing.value.status_code == 404

    evidence.build.side_effect = None
    evidence.build.return_value = Mock()
    analyzer.side_effect = ValueError("unsafe output")
    with pytest.raises(ApplicationError) as unsafe:
        asyncio.run(service.simulate(session, user_id=OWNER_ID, command=_command()))
    assert unsafe.value.status_code == 422
    repository.create.assert_not_awaited()
    assert monitor.record_failure.call_count == 2


def test_cancelled_request_waits_for_cpu_work_and_never_persists() -> None:
    started = threading.Event()
    release = threading.Event()

    def analyzer(*args, **kwargs):
        del args, kwargs
        started.set()
        assert release.wait(timeout=2)
        return Mock(name="analysis")

    evidence = AsyncMock(spec=ScenarioEvidenceService)
    evidence.build.return_value = Mock(name="snapshot")
    repository = AsyncMock(spec=ScenarioSimulationRepository)
    service = ScenarioSimulationService(
        evidence_service=evidence,
        repository=repository,
        analyzer=analyzer,
        monitor=Mock(spec=ScenarioSimulationMonitor),
        clock=FixedClock(),
    )
    service._monitor.start.return_value = 1.0

    async def exercise() -> None:
        task = asyncio.create_task(
            service.simulate(
                AsyncMock(spec=AsyncSession),
                user_id=OWNER_ID,
                command=_command(),
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    repository.create.assert_not_awaited()


def test_execution_guard_bounds_concurrency_rate_and_expires_old_owners() -> None:
    times = iter((0.0, 0.0, 0.0, 61.0))
    guard = ScenarioExecutionGuard(
        maximum=1,
        acquire_timeout_seconds=0.001,
        owner_rate_limit=1,
        rate_window_seconds=60,
        timer=lambda: next(times),
    )
    another_owner = uuid4()

    async def exercise() -> None:
        async with guard.slot(user_id=OWNER_ID):
            with pytest.raises(ScenarioExecutionBusyError):
                async with guard.slot(user_id=another_owner):
                    pass
        with pytest.raises(ScenarioRateLimitError):
            async with guard.slot(user_id=OWNER_ID):
                pass
        async with guard.slot(user_id=OWNER_ID):
            pass

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"maximum": 0},
        {"maximum": True},
        {"acquire_timeout_seconds": 0},
        {"owner_rate_limit": 0},
        {"owner_rate_limit": True},
        {"rate_window_seconds": 0},
    ],
)
def test_execution_guard_rejects_invalid_bounds(kwargs) -> None:
    with pytest.raises(ValueError):
        ScenarioExecutionGuard(**kwargs)
