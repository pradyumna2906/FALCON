"""Bounded privacy-safe monitoring for Phase 11 scenario operations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from time import perf_counter

from falcon_api.models.scenario import ScenarioSimulationRun
from falcon_api.scenario_simulation.monte_carlo import (
    MONTE_CARLO_PROBABILITY_METHOD,
)
from falcon_api.scenario_simulation.semantics import (
    ScenarioCalibrationReliability,
)


SCENARIO_OPERATION_POLICY_VERSION = "2026.1"


class ScenarioOperation(StrEnum):
    """Closed low-cardinality scenario operations."""

    SIMULATE = "simulate"
    REGENERATE = "regenerate"
    SELECT = "select"
    CLEAR_SELECTION = "clear_selection"


class ScenarioFailureReason(StrEnum):
    """Safe failure categories that reveal no resource identity or values."""

    CAPACITY_EXHAUSTED = "capacity_exhausted"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    SELECTION_CONFLICT = "selection_conflict"


class ScenarioSimulationMonitor:
    """Emit only bounded aggregate evidence without identities or exact money."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._logger = logger or logging.getLogger(
            "falcon_api.scenario_simulation"
        )
        self._timer = timer

    def start(self) -> float:
        return self._timer()

    def record_simulation(
        self,
        run: ScenarioSimulationRun,
        *,
        operation: ScenarioOperation,
        started_at: float,
    ) -> None:
        resolved = ScenarioOperation(operation)
        if resolved not in {
            ScenarioOperation.SIMULATE,
            ScenarioOperation.REGENERATE,
        }:
            raise ValueError("Scenario simulation telemetry operation is invalid.")
        if (
            run.scenario_count != len(run.definitions)
            or not 4 <= run.scenario_count <= 13
            or run.horizon_months < 0
            or run.trial_count < 1
            or run.probability_method != MONTE_CARLO_PROBABILITY_METHOD
        ):
            raise ValueError("Scenario simulation telemetry counts are invalid.")
        recommendation = next(
            (item for item in run.comparisons if item.recommended),
            None,
        )
        if recommendation is not None:
            definition = next(
                item
                for item in run.definitions
                if item.id == recommendation.scenario_definition_id
            )
            completion = definition.all_goals_completion_probability
            negative_risk = definition.negative_savings_probability
        else:
            completion = None
            negative_risk = None
        reliability = _aggregate_reliability(run)
        self._logger.info(
            "scenario_simulation_completed",
            extra={
                "scenario_operation_policy_version": (
                    SCENARIO_OPERATION_POLICY_VERSION
                ),
                "scenario_operation": resolved.value,
                "scenario_count_band": _count_band(run.scenario_count),
                "scenario_horizon_band": _horizon_band(run.horizon_months),
                "scenario_trial_band": _trial_band(run.trial_count),
                "scenario_probability_method": run.probability_method,
                "scenario_reliability": reliability.value,
                "scenario_completion_band": _probability_band(completion),
                "scenario_negative_savings_risk_band": _probability_band(
                    negative_risk
                ),
                "scenario_result": (
                    "recommended" if recommendation is not None else "no_safe_choice"
                ),
                "duration_ms": _duration_ms(self._timer(), started_at),
            },
        )

    def record_selection(
        self,
        *,
        operation: ScenarioOperation,
        started_at: float,
    ) -> None:
        resolved = ScenarioOperation(operation)
        if resolved not in {
            ScenarioOperation.SELECT,
            ScenarioOperation.CLEAR_SELECTION,
        }:
            raise ValueError("Scenario selection telemetry operation is invalid.")
        self._logger.info(
            "scenario_selection_completed",
            extra={
                "scenario_operation_policy_version": (
                    SCENARIO_OPERATION_POLICY_VERSION
                ),
                "scenario_operation": resolved.value,
                "scenario_result": "success",
                "duration_ms": _duration_ms(self._timer(), started_at),
            },
        )

    def record_failure(
        self,
        *,
        operation: ScenarioOperation,
        reason: ScenarioFailureReason,
        started_at: float,
    ) -> None:
        self._logger.info(
            "scenario_operation_failed",
            extra={
                "scenario_operation_policy_version": (
                    SCENARIO_OPERATION_POLICY_VERSION
                ),
                "scenario_operation": ScenarioOperation(operation).value,
                "scenario_result": "failed",
                "scenario_failure_reason": ScenarioFailureReason(reason).value,
                "duration_ms": _duration_ms(self._timer(), started_at),
            },
        )


def _aggregate_reliability(
    run: ScenarioSimulationRun,
) -> ScenarioCalibrationReliability:
    if not run.definitions:
        raise ValueError("Scenario telemetry requires at least one definition.")
    order = {
        ScenarioCalibrationReliability.NORMAL: 3,
        ScenarioCalibrationReliability.PROVISIONAL: 2,
        ScenarioCalibrationReliability.CONSERVATIVE: 1,
        ScenarioCalibrationReliability.UNAVAILABLE: 0,
    }
    return min(
        (
            ScenarioCalibrationReliability(item.reliability)
            for item in run.definitions
        ),
        key=order.__getitem__,
    )


def _count_band(value: int) -> str:
    if type(value) is not int or value < 0:
        raise ValueError("Scenario counts must be non-negative integers.")
    if value <= 4:
        return "001_004"
    if value <= 8:
        return "005_008"
    return "009_013"


def _horizon_band(value: int) -> str:
    if type(value) is not int or not 0 <= value <= 24:
        raise ValueError("Scenario horizon telemetry is out of bounds.")
    if value == 0:
        return "000"
    if value <= 3:
        return "001_003"
    if value <= 6:
        return "004_006"
    if value <= 12:
        return "007_012"
    return "013_024"


def _trial_band(value: int) -> str:
    if type(value) is not int or not 1 <= value <= 10_000:
        raise ValueError("Scenario trial telemetry is out of bounds.")
    if value <= 250:
        return "0001_0250"
    if value <= 1_000:
        return "0251_1000"
    if value <= 5_000:
        return "1001_5000"
    return "5001_10000"


def _probability_band(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    resolved = Decimal(value)
    if not resolved.is_finite() or not Decimal("0") <= resolved <= Decimal("1"):
        raise ValueError("Scenario probability telemetry is invalid.")
    if resolved < Decimal("0.25"):
        return "under_25_percent"
    if resolved < Decimal("0.50"):
        return "25_49_percent"
    if resolved < Decimal("0.75"):
        return "50_74_percent"
    if resolved < Decimal("1"):
        return "75_99_percent"
    return "100_percent"


def _duration_ms(finished_at: float, started_at: float) -> float:
    return round(max(0.0, (finished_at - started_at) * 1000), 3)
