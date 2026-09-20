"""Versioned Phase 11 scenario-simulation boundaries."""

from __future__ import annotations

from enum import StrEnum


SCENARIO_SIMULATION_CONTRACT_VERSION = "2026.1"
SCENARIO_PATH_POLICY_VERSION = "2026.1"
SCENARIO_REEVALUATION_POLICY_VERSION = "2026.1"
MAX_SCENARIOS_PER_REQUEST = 10
MAX_SCENARIO_HORIZON_MONTHS = 24
MAX_ONE_TIME_EXPENSES = 12
MAX_RECURRING_EXPENSE_ADJUSTMENTS = 12
MAX_INCOME_INTERRUPTION_PERIODS = 4
MAX_DEBT_PAYMENT_ADJUSTMENTS = 12
MAX_GOAL_ADJUSTMENTS = 100
MAX_SCENARIO_NAME_LENGTH = 80


class ScenarioErrorCode(StrEnum):
    """Stable application failures reserved by the Phase 11 boundary."""

    INVALID_ASSUMPTIONS = "scenario_invalid_assumptions"
    SOURCE_PLAN_NOT_FOUND = "scenario_source_plan_not_found"
    SOURCE_PLAN_UNAVAILABLE = "scenario_source_plan_unavailable"
    EVIDENCE_UNAVAILABLE = "scenario_evidence_unavailable"


class ScenarioCaseKind(StrEnum):
    """Closed deterministic alternatives evaluated before Monte Carlo."""

    PROTECTED = "protected"
    EXPECTED = "expected"
    UPSIDE = "upside"
    USER_DEFINED = "user_defined"


class ScenarioPathStatus(StrEnum):
    """Readiness of one deterministic capacity path."""

    AVAILABLE = "available"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


class ScenarioEvaluationStatus(StrEnum):
    """Final deterministic reevaluation outcome."""

    OPTIMIZED = "optimized"
    GUARDED_FALLBACK = "guarded_fallback"
    BLOCKED = "blocked"
    INFEASIBLE = "infeasible"
    UNAVAILABLE = "unavailable"


class ScenarioReasonCode(StrEnum):
    """Stable, non-generative explanations for deterministic scenarios."""

    PROTECTED_REFERENCE = "protected_reference"
    EXPECTED_REFERENCE = "expected_reference"
    UPSIDE_REFERENCE = "upside_reference"
    USER_ASSUMPTIONS_APPLIED = "user_assumptions_applied"
    SOURCE_SAVINGS_FORECAST_MISSING = "source_savings_forecast_missing"
    INCOME_FORECAST_REQUIRED = "income_forecast_required"
    EXPENSE_FORECAST_REQUIRED = "expense_forecast_required"
    PROVISIONAL_EVIDENCE = "provisional_evidence"
    NEGATIVE_CAPACITY_CLIPPED = "negative_capacity_clipped"
    CAPACITY_OUT_OF_RANGE = "capacity_out_of_range"
    EMERGENCY_RESERVE_APPLIED = "emergency_reserve_applied"
    EMERGENCY_RESERVE_RECALCULATED = "emergency_reserve_recalculated"
    CONTRIBUTION_CONSTRAINT_APPLIED = "contribution_constraint_applied"
    SOURCE_PLAN_BLOCKED = "source_plan_blocked"
    NO_PROTECTED_CAPACITY = "no_protected_capacity"
    NO_ELIGIBLE_GOALS = "no_eligible_goals"
    CONTRIBUTION_CONSTRAINT_INFEASIBLE = "contribution_constraint_infeasible"
    OPTIMIZED_SCHEDULE_SELECTED = "optimized_schedule_selected"
    GUARDED_FALLBACK_SELECTED = "guarded_fallback_selected"


class ScenarioSnapshotWarning(StrEnum):
    """Bounded warnings attached to an immutable scenario snapshot."""

    FORECAST_UNAVAILABLE = "forecast_unavailable"
    FORECAST_PROVISIONAL = "forecast_provisional"
    INCOME_FORECAST_UNAVAILABLE = "income_forecast_unavailable"
    INCOME_FORECAST_PROVISIONAL = "income_forecast_provisional"
    EXPENSE_FORECAST_UNAVAILABLE = "expense_forecast_unavailable"
    EXPENSE_FORECAST_PROVISIONAL = "expense_forecast_provisional"
    SOURCE_PLAN_GENERATED_ONLY = "source_plan_generated_only"
