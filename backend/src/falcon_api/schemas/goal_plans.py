"""Strict public contracts for persistent multi-goal optimization plans."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from falcon_api.goal_planning.feasibility import (
    FeasibilityEvidenceReliability,
    GoalDeadlineRiskLevel,
    GoalFeasibilityReasonCode,
    GoalFeasibilityState,
)
from falcon_api.goal_planning.guardrails import OptimizationGuardrailReasonCode
from falcon_api.goal_planning.plan import (
    GoalPlanAssumption,
    GoalPlanReasonCode,
    GoalPlanStrategy,
)
from falcon_api.goal_planning.ranking import GoalRankingReasonCode
from falcon_api.models.enums import (
    GoalPlanEventSource,
    GoalPlanStatus,
    GoalPriority,
    GoalType,
)


PlanCurrency = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$"),
]
PlanHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PlanMoney = Annotated[Decimal, Field(max_digits=19, decimal_places=4)]
PlanScore = Annotated[Decimal, Field(max_digits=20, decimal_places=6)]
PlanProbability = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=9, decimal_places=6),
]


class GoalPlanSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class GoalPlanGenerationRequest(GoalPlanSchema):
    """Allow only currency selection; all planning evidence remains server-owned."""

    currency: PlanCurrency | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class GoalPlanAllocationResponse(GoalPlanSchema):
    goal_id: UUID
    rank: int
    amount: PlanMoney
    cumulative_amount: PlanMoney
    projected_remaining_amount: PlanMoney


class GoalPlanPeriodResponse(GoalPlanSchema):
    period_start: date
    available_capacity: PlanMoney
    allocated_amount: PlanMoney
    unallocated_amount: PlanMoney
    allocations: tuple[GoalPlanAllocationResponse, ...]


class GoalPlanOutcomeResponse(GoalPlanSchema):
    goal_id: UUID
    goal_name: str
    goal_type: GoalType
    priority: GoalPriority
    target_date: date
    rank: int
    target_amount: PlanMoney
    current_amount: PlanMoney
    starting_remaining_amount: PlanMoney
    allocated_amount: PlanMoney
    projected_remaining_amount: PlanMoney
    protected_shortfall: PlanMoney
    expected_shortfall: PlanMoney
    expected_completion_period: date | None
    projected_completion_period: date | None
    deadline_met: bool
    feasibility_state: GoalFeasibilityState
    deadline_risk: GoalDeadlineRiskLevel
    completion_probability: PlanProbability | None
    evidence_reliability: FeasibilityEvidenceReliability
    feasibility_reason_codes: tuple[GoalFeasibilityReasonCode, ...]
    ranking_reason_codes: tuple[GoalRankingReasonCode, ...]


class GoalPlanEventResponse(GoalPlanSchema):
    previous_status: GoalPlanStatus | None
    status: GoalPlanStatus
    source: GoalPlanEventSource
    occurred_at: datetime
    successor_plan_id: UUID | None
    reason_code: str | None


class GoalPlanSummaryResponse(GoalPlanSchema):
    id: UUID
    deterministic_plan_id: PlanHash
    snapshot_id: PlanHash
    predecessor_plan_id: UUID | None
    successor_plan_id: UUID | None
    status: GoalPlanStatus
    created_at: datetime
    decided_at: datetime | None
    currency: PlanCurrency
    planning_cutoff_at: datetime
    horizon_start: date | None
    horizon_end: date | None
    strategy: GoalPlanStrategy
    overall_feasibility: str
    forecast_reliability: str
    available_savings: PlanMoney
    allocated_savings: PlanMoney
    unallocated_savings: PlanMoney
    weighted_funding_score: PlanScore
    goal_count: int
    feasible_goal_count: int
    at_risk_goal_count: int
    uncertain_goal_count: int
    fully_funded_goal_count: int
    deadline_met_goal_count: int


class GoalPlanRunResponse(GoalPlanSummaryResponse):
    forecast_run_id: UUID | None
    local_date: date
    timezone: str
    contract_version: str
    plan_policy_version: str
    capacity_policy_version: str | None
    feasibility_policy_version: str
    ranking_policy_version: str
    greedy_policy_version: str
    optimization_policy_version: str
    guardrail_policy_version: str
    optimizer_status: str | None
    solver_name: str | None
    solver_version: str | None
    allocation_band: str
    emergency_reserve_amount: PlanMoney
    greedy_weighted_funding_score: PlanScore
    guarded_fallback_weighted_funding_score: PlanScore
    optimized_weighted_funding_score: PlanScore | None
    selected_score_delta_from_greedy: PlanScore
    assumptions: tuple[GoalPlanAssumption, ...]
    reason_codes: tuple[GoalPlanReasonCode, ...]
    snapshot_warnings: tuple[str, ...]
    guardrail_reason_codes: tuple[OptimizationGuardrailReasonCode, ...]
    outcomes: tuple[GoalPlanOutcomeResponse, ...]
    periods: tuple[GoalPlanPeriodResponse, ...]
    events: tuple[GoalPlanEventResponse, ...]


class GoalPlanListResponse(GoalPlanSchema):
    items: tuple[GoalPlanSummaryResponse, ...]
