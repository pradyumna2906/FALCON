"""Checkpoint 11.11 immutable scenario persistence-model tests."""

from datetime import UTC, datetime
from uuid import uuid4

from falcon_api.infrastructure.persistence import model_metadata
from falcon_api.models import register_models
from falcon_api.models.enums import (
    ScenarioSimulationEventSource,
    ScenarioSimulationEventType,
)
from falcon_api.models.scenario import ScenarioEvent, ScenarioSimulationRun


_TABLES = {
    "scenario_simulation_runs",
    "scenario_definitions",
    "scenario_periods",
    "scenario_goal_outcomes",
    "scenario_comparisons",
    "scenario_events",
}


def test_scenario_models_register_complete_owner_scoped_graph() -> None:
    register_models()
    metadata = model_metadata()

    assert _TABLES <= set(metadata.tables)
    assert len(metadata.tables) == 34
    for table_name in _TABLES - {"scenario_simulation_runs"}:
        table = metadata.tables[table_name]
        assert {"user_id", "simulation_run_id"} <= set(table.columns.keys())
    run = metadata.tables["scenario_simulation_runs"]
    assert {"user_id", "source_plan_id", "snapshot_id", "root_seed"} <= set(
        run.columns.keys()
    )


def test_scenario_schema_excludes_private_source_and_raw_sample_payloads() -> None:
    register_models()
    columns = {
        column.name
        for table_name in _TABLES
        for column in model_metadata().tables[table_name].columns
    }

    assert not {
        "account_id",
        "transaction_id",
        "goal_name",
        "goal_description",
        "sample_buffer",
        "raw_samples",
    } & columns


def test_selected_scenario_is_derived_only_from_append_only_events() -> None:
    run_id = uuid4()
    owner_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    first_at = datetime(2026, 9, 20, 10, tzinfo=UTC)
    second_at = datetime(2026, 9, 20, 11, tzinfo=UTC)
    run = ScenarioSimulationRun(id=run_id, user_id=owner_id)
    run.events = [
        ScenarioEvent(
            user_id=owner_id,
            simulation_run_id=run_id,
            scenario_definition_id=first_id,
            event_type=ScenarioSimulationEventType.SELECTED,
            source=ScenarioSimulationEventSource.USER,
            occurred_at=first_at,
            reason_code="first",
        ),
        ScenarioEvent(
            user_id=owner_id,
            simulation_run_id=run_id,
            scenario_definition_id=second_id,
            event_type=ScenarioSimulationEventType.SELECTED,
            source=ScenarioSimulationEventSource.USER,
            occurred_at=second_at,
            reason_code="second",
        ),
    ]

    assert run.selected_scenario_id == second_id
    assert run.selected_at == second_at

    run.events.append(
        ScenarioEvent(
            user_id=owner_id,
            simulation_run_id=run_id,
            scenario_definition_id=None,
            event_type=ScenarioSimulationEventType.SELECTION_CLEARED,
            source=ScenarioSimulationEventSource.USER,
            occurred_at=datetime(2026, 9, 20, 12, tzinfo=UTC),
            reason_code="cleared",
        )
    )
    assert run.selected_scenario_id is None
