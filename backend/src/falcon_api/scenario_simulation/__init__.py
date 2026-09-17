"""Public Phase 11 scenario-simulation contracts."""

from falcon_api.scenario_simulation.assumptions import (
    GoalScenarioAdjustment,
    IncomeInterruptionAssumption,
    OneTimeExpenseAssumption,
    RecurringExpenseAdjustment,
    ScenarioAssumptions,
    validate_scenario_assumptions,
)
from falcon_api.scenario_simulation.semantics import (
    MAX_GOAL_ADJUSTMENTS,
    MAX_INCOME_INTERRUPTION_PERIODS,
    MAX_ONE_TIME_EXPENSES,
    MAX_RECURRING_EXPENSE_ADJUSTMENTS,
    MAX_SCENARIO_HORIZON_MONTHS,
    MAX_SCENARIO_NAME_LENGTH,
    MAX_SCENARIOS_PER_REQUEST,
    SCENARIO_SIMULATION_CONTRACT_VERSION,
    ScenarioErrorCode,
    ScenarioSnapshotWarning,
)
from falcon_api.scenario_simulation.repository import ScenarioForecastRepository
from falcon_api.scenario_simulation.snapshot import (
    ScenarioAllocationEvidence,
    ScenarioEvidenceService,
    ScenarioEvidenceSnapshot,
    ScenarioForecastEvidence,
    ScenarioForecastPointEvidence,
    ScenarioGoalEvidence,
    ScenarioPeriodEvidence,
    ScenarioSourcePlanEvidence,
)

__all__ = [
    "MAX_GOAL_ADJUSTMENTS",
    "MAX_INCOME_INTERRUPTION_PERIODS",
    "MAX_ONE_TIME_EXPENSES",
    "MAX_RECURRING_EXPENSE_ADJUSTMENTS",
    "MAX_SCENARIO_HORIZON_MONTHS",
    "MAX_SCENARIO_NAME_LENGTH",
    "MAX_SCENARIOS_PER_REQUEST",
    "SCENARIO_SIMULATION_CONTRACT_VERSION",
    "GoalScenarioAdjustment",
    "IncomeInterruptionAssumption",
    "OneTimeExpenseAssumption",
    "RecurringExpenseAdjustment",
    "ScenarioAssumptions",
    "ScenarioAllocationEvidence",
    "ScenarioEvidenceService",
    "ScenarioEvidenceSnapshot",
    "ScenarioErrorCode",
    "ScenarioForecastEvidence",
    "ScenarioForecastRepository",
    "ScenarioForecastPointEvidence",
    "ScenarioGoalEvidence",
    "ScenarioPeriodEvidence",
    "ScenarioSnapshotWarning",
    "ScenarioSourcePlanEvidence",
    "validate_scenario_assumptions",
]
