"""Checkpoint 11.14 bounded privacy-safe scenario telemetry tests."""

import json
import logging
from decimal import Decimal
from unittest.mock import Mock

import pytest

from falcon_api.core.logging import JsonLogFormatter
from falcon_api.scenario_simulation import (
    SCENARIO_OPERATION_POLICY_VERSION,
    ScenarioFailureReason,
    ScenarioOperation,
    ScenarioSimulationMonitor,
)
from falcon_api.scenario_simulation.monitoring import (
    _aggregate_reliability,
    _count_band,
    _horizon_band,
    _probability_band,
    _trial_band,
)
from scenario_test_data import transient_scenario_run


def test_simulation_monitor_emits_only_bounded_aggregate_evidence() -> None:
    logger = Mock()
    monitor = ScenarioSimulationMonitor(
        logger=logger,
        timer=Mock(side_effect=(10.0, 10.125)),
    )
    run = transient_scenario_run()

    started = monitor.start()
    monitor.record_simulation(
        run,
        operation=ScenarioOperation.SIMULATE,
        started_at=started,
    )

    assert logger.info.call_args.args == ("scenario_simulation_completed",)
    extra = logger.info.call_args.kwargs["extra"]
    assert extra == {
        "scenario_operation_policy_version": SCENARIO_OPERATION_POLICY_VERSION,
        "scenario_operation": "simulate",
        "scenario_count_band": "001_004",
        "scenario_horizon_band": "001_003",
        "scenario_trial_band": "0001_0250",
        "scenario_probability_method": "seeded_empirical_monte_carlo",
        "scenario_reliability": "normal",
        "scenario_completion_band": "100_percent",
        "scenario_negative_savings_risk_band": "under_25_percent",
        "scenario_result": "recommended",
        "duration_ms": 125.0,
    }
    serialized = repr(extra).lower()
    custom = next(item for item in run.definitions if item.assumptions is not None)
    for private_value in (
        run.user_id,
        run.id,
        custom.name,
        custom.capacity_total,
        custom.allocated_total,
        custom.assumptions["name"],
    ):
        assert str(private_value).lower() not in serialized


def test_scenario_fields_survive_the_json_allowlist_without_private_values() -> None:
    logger = logging.getLogger("test.scenario.monitor")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "scenario_simulation_completed",
        (),
        None,
        extra={
            "scenario_operation_policy_version": "2026.1",
            "scenario_operation": "simulate",
            "scenario_count_band": "001_004",
            "scenario_horizon_band": "001_003",
            "scenario_trial_band": "0001_0250",
            "scenario_probability_method": "seeded_empirical_monte_carlo",
            "scenario_reliability": "normal",
            "scenario_completion_band": "75_99_percent",
            "scenario_negative_savings_risk_band": "under_25_percent",
            "scenario_result": "recommended",
            "scenario_failure_reason": "capacity_exhausted",
            "user_id": "must-not-leak",
            "exact_allocation": "must-not-leak",
        },
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["scenario_operation"] == "simulate"
    assert payload["scenario_result"] == "recommended"
    assert payload["scenario_failure_reason"] == "capacity_exhausted"
    assert "user_id" not in payload
    assert "exact_allocation" not in payload


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (None, "unavailable"),
        ("0", "under_25_percent"),
        ("0.25", "25_49_percent"),
        ("0.50", "50_74_percent"),
        ("0.75", "75_99_percent"),
        ("1", "100_percent"),
    ],
)
def test_monitor_buckets_probability_without_exact_values(
    probability,
    expected,
) -> None:
    run = transient_scenario_run()
    comparison = next(item for item in run.comparisons if item.recommended)
    definition = next(
        item
        for item in run.definitions
        if item.id == comparison.scenario_definition_id
    )
    definition.all_goals_completion_probability = (
        Decimal(probability) if probability is not None else None
    )
    logger = Mock()

    ScenarioSimulationMonitor(logger=logger, timer=lambda: 1.0).record_simulation(
        run,
        operation=ScenarioOperation.REGENERATE,
        started_at=1.0,
    )

    assert logger.info.call_args.kwargs["extra"]["scenario_completion_band"] == (
        expected
    )


@pytest.mark.parametrize(
    "change",
    [
        {"scenario_count": 3},
        {"scenario_count": 14},
        {"horizon_months": -1},
        {"horizon_months": 25},
        {"trial_count": 0},
        {"trial_count": 10_001},
        {"probability_method": "private-user-value"},
    ],
)
def test_monitor_rejects_unbounded_run_metadata(change) -> None:
    run = transient_scenario_run()
    for name, value in change.items():
        setattr(run, name, value)

    with pytest.raises(ValueError):
        ScenarioSimulationMonitor(logger=Mock(), timer=lambda: 1.0).record_simulation(
            run,
            operation=ScenarioOperation.SIMULATE,
            started_at=1.0,
        )


def test_monitor_handles_no_recommendation_and_rejects_invalid_evidence() -> None:
    run = transient_scenario_run()
    recommended = next(item for item in run.comparisons if item.recommended)
    recommended.recommended = False
    logger = Mock()
    ScenarioSimulationMonitor(logger=logger, timer=lambda: 1.0).record_simulation(
        run,
        operation=ScenarioOperation.SIMULATE,
        started_at=2.0,
    )
    assert logger.info.call_args.kwargs["extra"]["scenario_result"] == (
        "no_safe_choice"
    )
    assert logger.info.call_args.kwargs["extra"]["duration_ms"] == 0.0

    run.definitions[0].reliability = "private"
    with pytest.raises(ValueError):
        ScenarioSimulationMonitor(logger=Mock()).record_simulation(
            run,
            operation=ScenarioOperation.SIMULATE,
            started_at=0.0,
        )


def test_selection_and_failure_monitoring_is_bounded() -> None:
    logger = Mock()
    monitor = ScenarioSimulationMonitor(logger=logger, timer=lambda: 2.25)
    monitor.record_selection(
        operation=ScenarioOperation.SELECT,
        started_at=2.0,
    )
    assert logger.info.call_args.kwargs["extra"] == {
        "scenario_operation_policy_version": "2026.1",
        "scenario_operation": "select",
        "scenario_result": "success",
        "duration_ms": 250.0,
    }

    monitor.record_failure(
        operation=ScenarioOperation.REGENERATE,
        reason=ScenarioFailureReason.RATE_LIMITED,
        started_at=2.0,
    )
    assert logger.info.call_args.kwargs["extra"]["scenario_failure_reason"] == (
        "rate_limited"
    )


def test_monitor_rejects_operation_category_mismatches() -> None:
    monitor = ScenarioSimulationMonitor(logger=Mock())
    with pytest.raises(ValueError, match="simulation telemetry"):
        monitor.record_simulation(
            transient_scenario_run(),
            operation=ScenarioOperation.SELECT,
            started_at=0.0,
        )
    with pytest.raises(ValueError, match="selection telemetry"):
        monitor.record_selection(
            operation=ScenarioOperation.SIMULATE,
            started_at=0.0,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4, "001_004"), (5, "005_008"), (9, "009_013")],
)
def test_count_bands_are_closed(value, expected) -> None:
    assert _count_band(value) == expected


@pytest.mark.parametrize("value", [-1, False])
def test_count_bands_reject_invalid_values(value) -> None:
    with pytest.raises(ValueError):
        _count_band(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "000"),
        (1, "001_003"),
        (4, "004_006"),
        (7, "007_012"),
        (13, "013_024"),
    ],
)
def test_horizon_bands_are_closed(value, expected) -> None:
    assert _horizon_band(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "0001_0250"),
        (251, "0251_1000"),
        (1_001, "1001_5000"),
        (5_001, "5001_10000"),
    ],
)
def test_trial_bands_are_closed(value, expected) -> None:
    assert _trial_band(value) == expected


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("-0.1"), Decimal("1.1")])
def test_probability_bands_reject_invalid_values(value) -> None:
    with pytest.raises(ValueError):
        _probability_band(value)


def test_aggregate_monitor_rejects_empty_definitions() -> None:
    run = transient_scenario_run()
    run.definitions = []
    with pytest.raises(ValueError):
        _aggregate_reliability(run)
