"""Strict request contracts reserved for Phase 11 scenario simulation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from falcon_api.models.enums import GoalPriority
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


class ScenarioSchema(BaseModel):
    """Reject unknown and mutable fields at the public contract boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


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
    """Future API payload containing only a source plan and hypothetical inputs."""

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
