"""Versioned Phase 11 scenario-simulation boundaries."""

from __future__ import annotations

from enum import StrEnum


SCENARIO_SIMULATION_CONTRACT_VERSION = "2026.1"
MAX_SCENARIOS_PER_REQUEST = 10
MAX_SCENARIO_HORIZON_MONTHS = 24
MAX_ONE_TIME_EXPENSES = 12
MAX_RECURRING_EXPENSE_ADJUSTMENTS = 12
MAX_INCOME_INTERRUPTION_PERIODS = 4
MAX_GOAL_ADJUSTMENTS = 100
MAX_SCENARIO_NAME_LENGTH = 80


class ScenarioErrorCode(StrEnum):
    """Stable application failures reserved by the Phase 11 boundary."""

    INVALID_ASSUMPTIONS = "scenario_invalid_assumptions"
    SOURCE_PLAN_NOT_FOUND = "scenario_source_plan_not_found"
    SOURCE_PLAN_UNAVAILABLE = "scenario_source_plan_unavailable"
    EVIDENCE_UNAVAILABLE = "scenario_evidence_unavailable"


class ScenarioSnapshotWarning(StrEnum):
    """Bounded warnings attached to an immutable scenario snapshot."""

    FORECAST_UNAVAILABLE = "forecast_unavailable"
    FORECAST_PROVISIONAL = "forecast_provisional"
    INCOME_FORECAST_UNAVAILABLE = "income_forecast_unavailable"
    INCOME_FORECAST_PROVISIONAL = "income_forecast_provisional"
    EXPENSE_FORECAST_UNAVAILABLE = "expense_forecast_unavailable"
    EXPENSE_FORECAST_PROVISIONAL = "expense_forecast_provisional"
    SOURCE_PLAN_GENERATED_ONLY = "source_plan_generated_only"
