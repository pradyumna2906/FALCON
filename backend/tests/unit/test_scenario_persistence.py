"""Checkpoint 11.11 scenario repository and selection-history tests."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from falcon_api.models.enums import ScenarioSimulationEventType
from falcon_api.scenario_simulation import (
    MonteCarloConfig,
    OneTimeExpenseAssumption,
    ScenarioAssumptions,
    ScenarioSimulationRepository,
    analyze_scenario_decisions,
)
from goal_plan_test_data import ZeroSolver
from scenario_test_data import transient_scenario_snapshot


def _evidence():
    snapshot = transient_scenario_snapshot(
        (
            ScenarioAssumptions(
                name="Unexpected expense",
                one_time_expenses=(
                    OneTimeExpenseAssumption(
                        date(2026, 10, 1),
                        Decimal("25"),
                    ),
                ),
            ),
        )
    )
    analysis = analyze_scenario_decisions(
        snapshot,
        config=MonteCarloConfig(trial_count=64, seed=23),
        solver=ZeroSolver(),
    )
    return snapshot, analysis


def _session() -> AsyncMock:
    session = AsyncMock()
    session.add = Mock()
    return session


def test_create_freezes_complete_replayable_graph() -> None:
    snapshot, analysis = _evidence()
    session = _session()
    repository = ScenarioSimulationRepository()
    occurred_at = snapshot.cutoff_at + timedelta(seconds=1)

    run = asyncio.run(
        repository.create(
            session,
            user_id=snapshot.user_id,
            snapshot=snapshot,
            analysis=analysis,
            occurred_at=occurred_at,
        )
    )

    assert run.snapshot_id == snapshot.snapshot_id
    assert run.analysis_id == analysis.analysis_id
    assert run.source_plan_id == snapshot.source_plan.run_id
    assert run.root_seed == 23
    assert run.trial_count == 64
    assert len(run.definitions) == len(analysis.alternatives) == 4
    assert len(run.comparisons) == 4
    assert all(len(item.periods) == len(snapshot.periods) for item in run.definitions)
    assert all(len(item.outcomes) == len(snapshot.goals) for item in run.definitions)
    assert run.events[0].event_type is ScenarioSimulationEventType.GENERATED
    assert run.events[0].occurred_at == occurred_at
    assert not hasattr(run, "raw_samples")
    session.add.assert_called_once_with(run)
    session.flush.assert_awaited_once()


def test_create_preserves_input_order_separately_from_decision_rank() -> None:
    scenarios = tuple(
        ScenarioAssumptions(
            name=name,
            one_time_expenses=(
                OneTimeExpenseAssumption(
                    date(2026, 10, 1),
                    Decimal(amount),
                ),
            ),
        )
        for name, amount in (
            ("Larger expense", "75"),
            ("Smaller expense", "25"),
        )
    )
    snapshot = transient_scenario_snapshot(scenarios)
    analysis = analyze_scenario_decisions(
        snapshot,
        config=MonteCarloConfig(trial_count=32, seed=23),
        solver=ZeroSolver(),
    )

    run = asyncio.run(
        ScenarioSimulationRepository().create(
            _session(),
            user_id=snapshot.user_id,
            snapshot=snapshot,
            analysis=analysis,
            occurred_at=snapshot.cutoff_at + timedelta(seconds=1),
        )
    )

    assert [item.ordinal for item in run.definitions] == [1, 2, 3, 4, 5]
    assert [item.name for item in run.definitions[3:]] == [
        "Larger expense",
        "Smaller expense",
    ]
    assert [
        item.path.name
        for item in analysis.alternatives
        if item.path.assumptions is not None
    ] == ["Smaller expense", "Larger expense"]


def test_create_rejects_owner_time_identity_and_seed_mismatches() -> None:
    snapshot, analysis = _evidence()
    repository = ScenarioSimulationRepository()
    session = _session()

    async def create(**changes):
        arguments = {
            "session": session,
            "user_id": snapshot.user_id,
            "snapshot": snapshot,
            "analysis": analysis,
            "occurred_at": snapshot.cutoff_at + timedelta(seconds=1),
        }
        arguments.update(changes)
        return await repository.create(**arguments)

    with pytest.raises(ValueError, match="owner"):
        asyncio.run(create(user_id=uuid4()))
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(create(occurred_at=datetime(2026, 9, 20, 12)))
    with pytest.raises(ValueError, match="identity"):
        asyncio.run(create(analysis=replace(analysis, analysis_id="0" * 64)))
    changed = replace(
        analysis.alternatives[0].risk,
        seed=analysis.root_seed + 1,
    )
    alternative = replace(analysis.alternatives[0], risk=changed)
    with pytest.raises(ValueError, match="replay seed"):
        asyncio.run(
            create(
                analysis=replace(
                    analysis,
                    alternatives=(alternative, *analysis.alternatives[1:]),
                )
            )
        )


def test_get_and_history_queries_are_strictly_owner_scoped() -> None:
    repository = ScenarioSimulationRepository()
    session = _session()
    owner_id = uuid4()
    run_id = uuid4()
    session.scalar.return_value = None
    session.scalars.return_value = Mock(all=Mock(return_value=[]))

    assert (
        asyncio.run(
            repository.get(
                session,
                user_id=owner_id,
                run_id=run_id,
                for_update=True,
            )
        )
        is None
    )
    assert asyncio.run(
        repository.list_recent(session, user_id=owner_id, limit=10)
    ) == ()
    with pytest.raises(ValueError, match="between 1 and 100"):
        asyncio.run(repository.list_recent(session, user_id=owner_id, limit=0))
    assert "scenario_simulation_runs.user_id" in str(
        session.scalar.await_args.args[0]
    )
    assert "FOR UPDATE" in str(session.scalar.await_args.args[0])
    assert "scenario_simulation_runs.user_id" in str(
        session.scalars.await_args.args[0]
    )


def test_selection_switch_and_clear_are_append_only_and_race_safe() -> None:
    snapshot, analysis = _evidence()
    session = _session()
    repository = ScenarioSimulationRepository()
    generated_at = snapshot.cutoff_at + timedelta(seconds=1)
    run = asyncio.run(
        repository.create(
            session,
            user_id=snapshot.user_id,
            snapshot=snapshot,
            analysis=analysis,
            occurred_at=generated_at,
        )
    )
    first_id, second_id = (item.id for item in run.definitions[:2])

    asyncio.run(
        repository.select(
            session,
            run=run,
            user_id=snapshot.user_id,
            scenario_definition_id=first_id,
            occurred_at=generated_at + timedelta(seconds=1),
        )
    )
    asyncio.run(
        repository.select(
            session,
            run=run,
            user_id=snapshot.user_id,
            scenario_definition_id=second_id,
            occurred_at=generated_at + timedelta(seconds=2),
        )
    )
    assert run.selected_scenario_id == second_id
    assert [item.event_type for item in run.events] == [
        ScenarioSimulationEventType.GENERATED,
        ScenarioSimulationEventType.SELECTED,
        ScenarioSimulationEventType.SELECTED,
    ]

    with pytest.raises(ValueError, match="state changed"):
        asyncio.run(
            repository.clear_selection(
                session,
                run=run,
                user_id=snapshot.user_id,
                expected_scenario_definition_id=first_id,
                occurred_at=generated_at + timedelta(seconds=3),
            )
        )
    asyncio.run(
        repository.clear_selection(
            session,
            run=run,
            user_id=snapshot.user_id,
            expected_scenario_definition_id=second_id,
            occurred_at=generated_at + timedelta(seconds=3),
        )
    )
    assert run.selected_scenario_id is None
    assert run.events[-1].event_type is ScenarioSimulationEventType.SELECTION_CLEARED

    with pytest.raises(ValueError, match="trusted owner"):
        asyncio.run(
            repository.select(
                session,
                run=run,
                user_id=uuid4(),
                scenario_definition_id=first_id,
                occurred_at=generated_at + timedelta(seconds=4),
            )
        )
    with pytest.raises(ValueError, match="chronological"):
        asyncio.run(
            repository.select(
                session,
                run=run,
                user_id=snapshot.user_id,
                scenario_definition_id=first_id,
                occurred_at=generated_at,
            )
        )
