"""Strict public request and response contracts for scenario simulation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from falcon_api.models.enums import (
    GoalPriority,
    ScenarioSimulationEventSource,
    ScenarioSimulationEventType,
)
from falcon_api.scenario_simulation.assumptions import (
    DebtPaymentAdjustment,
    GoalScenarioAdjustment,
    IncomeInterruptionAssumption,
    OneTimeExpenseAssumption,
    RecurringExpenseAdjustment,
    ScenarioAssumptions,
    validate_scenario_assumptions,
)
from falcon_api.scenario_simulation.semantics import (
    MAX_DEBT_PAYMENT_ADJUSTMENTS,
    MAX_GOAL_ADJUSTMENTS,
    MAX_INCOME_INTERRUPTION_PERIODS,
    MAX_ONE_TIME_EXPENSES,
    MAX_RECURRING_EXPENSE_ADJUSTMENTS,
    MAX_SCENARIO_NAME_LENGTH,
    MAX_SCENARIOS_PER_REQUEST,
)


ScenarioName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SCENARIO_NAME_LENGTH),
]
ScenarioMoney = Annotated[
    Decimal,
    Field(max_digits=19, decimal_places=4),
]
ScenarioPercentage = Annotated[
    Decimal,
    Field(ge=Decimal("-100"), le=Decimal("300"), max_digits=8, decimal_places=4),
]
ScenarioHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ScenarioProbability = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=9, decimal_places=6),
]
ScenarioScore = Annotated[
    Decimal,
    Field(ge=Decimal("0"), max_digits=20, decimal_places=6),
]


class ScenarioSchema(BaseModel):
    """Reject unknown and mutable fields at the public contract boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class OneTimeExpenseRequest(ScenarioSchema):
    period_start: date
    amount: Annotated[ScenarioMoney, Field(gt=0)]

    def to_domain(self) -> OneTimeExpenseAssumption:
        return OneTimeExpenseAssumption(
            period_start=self.period_start,
            amount=self.amount,
        )


class RecurringExpenseAdjustmentRequest(ScenarioSchema):
    start_period: date
    end_period: date
    monthly_delta: ScenarioMoney

    def to_domain(self) -> RecurringExpenseAdjustment:
        return RecurringExpenseAdjustment(
            start_period=self.start_period,
            end_period=self.end_period,
            monthly_delta=self.monthly_delta,
        )


class DebtPaymentAdjustmentRequest(ScenarioSchema):
    start_period: date
    end_period: date
    monthly_delta: ScenarioMoney

    def to_domain(self) -> DebtPaymentAdjustment:
        return DebtPaymentAdjustment(
            start_period=self.start_period,
            end_period=self.end_period,
            monthly_delta=self.monthly_delta,
        )


class IncomeInterruptionRequest(ScenarioSchema):
    start_period: date
    end_period: date
    retained_income_percent: Annotated[
        Decimal,
        Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=4),
    ] = Decimal("0")

    def to_domain(self) -> IncomeInterruptionAssumption:
        return IncomeInterruptionAssumption(
            start_period=self.start_period,
            end_period=self.end_period,
            retained_income_percent=self.retained_income_percent,
        )


class GoalScenarioAdjustmentRequest(ScenarioSchema):
    goal_id: UUID
    target_amount: Annotated[ScenarioMoney, Field(gt=0)] | None = None
    target_date: date | None = None
    priority: GoalPriority | None = None
    monthly_contribution_delta: ScenarioMoney | None = None
    pause_start: date | None = None
    pause_end: date | None = None

    def to_domain(self) -> GoalScenarioAdjustment:
        return GoalScenarioAdjustment(
            goal_id=self.goal_id,
            target_amount=self.target_amount,
            target_date=self.target_date,
            priority=self.priority,
            monthly_contribution_delta=self.monthly_contribution_delta,
            pause_start=self.pause_start,
            pause_end=self.pause_end,
        )


class ScenarioDefinitionRequest(ScenarioSchema):
    """One bounded user-defined alternative; standard cases remain server-owned."""

    name: ScenarioName
    income_change_percent: ScenarioPercentage = Decimal("0")
    expense_change_percent: ScenarioPercentage = Decimal("0")
    one_time_expenses: Annotated[
        tuple[OneTimeExpenseRequest, ...],
        Field(max_length=MAX_ONE_TIME_EXPENSES),
    ] = ()
    recurring_expense_adjustments: Annotated[
        tuple[RecurringExpenseAdjustmentRequest, ...],
        Field(max_length=MAX_RECURRING_EXPENSE_ADJUSTMENTS),
    ] = ()
    debt_payment_adjustments: Annotated[
        tuple[DebtPaymentAdjustmentRequest, ...],
        Field(max_length=MAX_DEBT_PAYMENT_ADJUSTMENTS),
    ] = ()
    income_interruptions: Annotated[
        tuple[IncomeInterruptionRequest, ...],
        Field(max_length=MAX_INCOME_INTERRUPTION_PERIODS),
    ] = ()
    goal_adjustments: Annotated[
        tuple[GoalScenarioAdjustmentRequest, ...],
        Field(max_length=MAX_GOAL_ADJUSTMENTS),
    ] = ()
    emergency_fund_target_months: Annotated[
        Decimal,
        Field(ge=0, le=24, max_digits=6, decimal_places=4),
    ] | None = None

    @model_validator(mode="after")
    def validate_domain_contract(self) -> ScenarioDefinitionRequest:
        self.to_domain()
        return self

    def to_domain(self) -> ScenarioAssumptions:
        return ScenarioAssumptions(
            name=self.name,
            income_change_percent=self.income_change_percent,
            expense_change_percent=self.expense_change_percent,
            one_time_expenses=tuple(item.to_domain() for item in self.one_time_expenses),
            recurring_expense_adjustments=tuple(
                item.to_domain() for item in self.recurring_expense_adjustments
            ),
            debt_payment_adjustments=tuple(
                item.to_domain() for item in self.debt_payment_adjustments
            ),
            income_interruptions=tuple(
                item.to_domain() for item in self.income_interruptions
            ),
            goal_adjustments=tuple(item.to_domain() for item in self.goal_adjustments),
            emergency_fund_target_months=self.emergency_fund_target_months,
        )


class ScenarioSimulationDraftRequest(ScenarioSchema):
    """Payload containing only a source plan and bounded hypothetical inputs."""

    source_plan_id: UUID
    scenarios: Annotated[
        tuple[ScenarioDefinitionRequest, ...],
        Field(min_length=1, max_length=MAX_SCENARIOS_PER_REQUEST),
    ]

    @model_validator(mode="after")
    def validate_scenario_set(self) -> ScenarioSimulationDraftRequest:
        validate_scenario_assumptions(self.to_domain())
        return self

    def to_domain(self) -> tuple[ScenarioAssumptions, ...]:
        return tuple(item.to_domain() for item in self.scenarios)


class ScenarioSelectionRequest(ScenarioSchema):
    """Compare-and-set a selection; a null target clears the current choice."""

    scenario_definition_id: UUID | None
    expected_selected_scenario_id: UUID | None = None


class ScenarioPeriodResponse(ScenarioSchema):
    period_start: date
    source_capacity: ScenarioMoney
    income_delta: ScenarioMoney
    expense_delta: ScenarioMoney
    one_time_expense: ScenarioMoney
    recurring_expense_delta: ScenarioMoney
    debt_payment_delta: ScenarioMoney
    raw_protected_amount: ScenarioMoney
    raw_expected_amount: ScenarioMoney
    raw_upside_amount: ScenarioMoney
    selected_capacity: ScenarioMoney
    allocated_amount: ScenarioMoney
    unallocated_amount: ScenarioMoney


class ScenarioGoalOutcomeResponse(ScenarioSchema):
    goal_id: UUID
    rank: int
    feasibility_state: str
    deadline_risk: str
    allocated_amount: ScenarioMoney
    projected_remaining_amount: ScenarioMoney
    protected_shortfall: ScenarioMoney
    expected_shortfall: ScenarioMoney
    deterministic_completion_probability: ScenarioProbability | None
    empirical_completion_probability: ScenarioProbability | None
    deadline_met_probability: ScenarioProbability | None
    completion_count: int
    completion_denominator: int
    deadline_met_count: int
    deadline_denominator: int
    completion_period_p10: date | None
    completion_period_p50: date | None
    completion_period_p90: date | None
    empirical_expected_shortfall: ScenarioMoney | None
    empirical_shortfall_p90: ScenarioMoney | None
    deterministic_deadline_met: bool


class ScenarioSensitivitySignalResponse(ScenarioSchema):
    factor: str
    occurrence_count: int
    direct_capacity_effect: ScenarioMoney
    influence_score: Annotated[
        Decimal,
        Field(ge=Decimal("0"), le=Decimal("100"), max_digits=9, decimal_places=4),
    ]
    method: str


class ScenarioComparisonResponse(ScenarioSchema):
    scenario_definition_id: UUID
    baseline_definition_id: UUID
    dominated_by_definition_id: UUID | None
    comparison_hash: ScenarioHash
    expected_capacity_delta: ScenarioMoney | None
    completion_probability_delta: Decimal | None
    deadline_probability_delta: Decimal | None
    reserve_probability_delta: Decimal | None
    negative_savings_probability_delta: Decimal | None
    expected_shortfall_delta: ScenarioMoney | None
    tail_shortfall_delta: ScenarioMoney | None
    robustness_delta: Decimal | None
    weighted_funding_delta: Decimal
    fully_funded_goal_delta: int
    deadline_met_goal_delta: int
    additional_required_contribution: ScenarioMoney
    decision_score: Annotated[
        Decimal,
        Field(ge=Decimal("0"), le=Decimal("100"), max_digits=9, decimal_places=4),
    ]
    rank: int
    recommended: bool
    sensitivity_signals: tuple[ScenarioSensitivitySignalResponse, ...]
    reason_codes: tuple[str, ...]


class ScenarioDefinitionSummaryResponse(ScenarioSchema):
    id: UUID
    ordinal: int
    name: str
    kind: str
    evaluation_status: str
    risk_status: str
    selected_band: str
    reliability: str
    emergency_reserve_amount: ScenarioMoney
    capacity_total: ScenarioMoney
    allocated_total: ScenarioMoney
    unallocated_total: ScenarioMoney
    weighted_funding_score: ScenarioScore
    all_goals_completion_probability: ScenarioProbability | None
    all_deadlines_met_probability: ScenarioProbability | None
    reserve_coverage_probability: ScenarioProbability | None
    negative_savings_probability: ScenarioProbability | None
    constraint_feasibility_probability: ScenarioProbability | None
    expected_capacity: ScenarioMoney | None
    expected_total_shortfall: ScenarioMoney | None
    tail_expected_shortfall_90: ScenarioMoney | None
    robustness_score: Annotated[
        Decimal,
        Field(ge=Decimal("0"), le=Decimal("100"), max_digits=9, decimal_places=4),
    ] | None


class ScenarioDefinitionResponse(ScenarioDefinitionSummaryResponse):
    path_id: ScenarioHash
    evaluation_id: ScenarioHash
    risk_id: ScenarioHash
    simulation_id: ScenarioHash
    assumptions: ScenarioDefinitionRequest | None
    reason_codes: tuple[str, ...]
    periods: tuple[ScenarioPeriodResponse, ...]
    outcomes: tuple[ScenarioGoalOutcomeResponse, ...]


class ScenarioEventResponse(ScenarioSchema):
    scenario_definition_id: UUID | None
    event_type: ScenarioSimulationEventType
    source: ScenarioSimulationEventSource
    occurred_at: datetime
    reason_code: str | None


class ScenarioSimulationSummaryResponse(ScenarioSchema):
    id: UUID
    source_plan_id: UUID
    snapshot_id: ScenarioHash
    analysis_id: ScenarioHash
    baseline_path_id: ScenarioHash
    currency: str
    cutoff_at: datetime
    horizon_start: date | None
    horizon_end: date | None
    horizon_months: int
    trial_count: int
    scenario_count: int
    probability_method: str
    selected_scenario_id: UUID | None
    selected_at: datetime | None
    created_at: datetime


class ScenarioSimulationRunResponse(ScenarioSimulationSummaryResponse):
    local_date: date
    timezone: str
    contract_version: str
    comparison_policy_version: str
    sensitivity_policy_version: str
    decision_policy_version: str
    persistence_policy_version: str
    monte_carlo_policy_version: str
    risk_policy_version: str
    percentile_method: str
    root_seed: int
    snapshot_warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    definitions: tuple[ScenarioDefinitionResponse, ...]
    comparisons: tuple[ScenarioComparisonResponse, ...]
    events: tuple[ScenarioEventResponse, ...]


class ScenarioSimulationListResponse(ScenarioSchema):
    items: tuple[ScenarioSimulationSummaryResponse, ...]


class ScenarioComparisonListResponse(ScenarioSchema):
    simulation_run_id: UUID
    snapshot_id: ScenarioHash
    baseline_scenario_id: UUID
    recommended_scenario_id: UUID | None
    definitions: tuple[ScenarioDefinitionSummaryResponse, ...]
    items: tuple[ScenarioComparisonResponse, ...]
