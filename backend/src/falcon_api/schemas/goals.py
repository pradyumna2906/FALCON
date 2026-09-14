"""Strict public contracts for Phase 10 goal management."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from falcon_api.goal_planning.progress import GoalFundingState
from falcon_api.goal_planning.snapshot import PlanningSnapshotWarning
from falcon_api.models.enums import (
    ContributionSourceType,
    GoalPriority,
    GoalStatus,
    GoalType,
    ProfileCompletionStatus,
)


GoalName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
GoalDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]
GoalCurrency = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$"),
]
GoalMoney = Annotated[
    Decimal,
    Field(max_digits=19, decimal_places=4),
]
PositiveGoalMoney = Annotated[
    Decimal,
    Field(gt=Decimal("0"), max_digits=19, decimal_places=4),
]
NonNegativeGoalMoney = Annotated[
    Decimal,
    Field(ge=Decimal("0"), max_digits=19, decimal_places=4),
]


class GoalSchema(BaseModel):
    """Forbid undeclared values and freeze validated goal payloads."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )


class GoalCreateRequest(GoalSchema):
    """Create one active goal for the authenticated principal."""

    name: GoalName
    goal_type: GoalType
    target_amount: PositiveGoalMoney
    starting_amount: NonNegativeGoalMoney = Decimal("0")
    currency: GoalCurrency | None = None
    target_date: date
    priority: GoalPriority = GoalPriority.MEDIUM
    description: GoalDescription | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("description", mode="before")
    @classmethod
    def normalize_blank_description(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_amounts(self) -> "GoalCreateRequest":
        if self.starting_amount > self.target_amount:
            raise ValueError("Starting amount cannot exceed the target amount.")
        return self


class GoalUpdateRequest(GoalSchema):
    """Partially replace mutable values on one active goal."""

    name: GoalName | None = None
    goal_type: GoalType | None = None
    target_amount: PositiveGoalMoney | None = None
    starting_amount: NonNegativeGoalMoney | None = None
    currency: GoalCurrency | None = None
    target_date: date | None = None
    priority: GoalPriority | None = None
    description: GoalDescription | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("description", mode="before")
    @classmethod
    def normalize_blank_description(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_partial_update(self) -> "GoalUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one goal field must be supplied.")
        required_values = self.model_fields_set - {"description"}
        if any(getattr(self, field) is None for field in required_values):
            raise ValueError("Goal fields other than description cannot be null.")
        if (
            "target_amount" in self.model_fields_set
            and "starting_amount" in self.model_fields_set
            and self.target_amount is not None
            and self.starting_amount is not None
            and self.starting_amount > self.target_amount
        ):
            raise ValueError("Starting amount cannot exceed the target amount.")
        return self


class GoalResponse(GoalSchema):
    """Expose a goal without returning its ownership key."""

    id: UUID
    name: GoalName
    goal_type: GoalType
    target_amount: GoalMoney
    starting_amount: GoalMoney
    currency: GoalCurrency
    target_date: date
    priority: GoalPriority
    status: GoalStatus
    description: GoalDescription | None
    created_at: datetime
    updated_at: datetime


class GoalListResponse(GoalSchema):
    """Return a bounded list of goals owned by the principal."""

    items: tuple[GoalResponse, ...]


class ContributionCreateRequest(GoalSchema):
    """Create one allocation with explicit provenance."""

    source_type: ContributionSourceType
    amount: PositiveGoalMoney
    contribution_date: date | None = None
    transaction_id: UUID | None = None
    note: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ] | None = None

    @field_validator("note", mode="before")
    @classmethod
    def normalize_blank_note(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_source_fields(self) -> "ContributionCreateRequest":
        if self.source_type is ContributionSourceType.TRANSACTION:
            if self.transaction_id is None or self.contribution_date is not None:
                raise ValueError(
                    "Transaction contributions require only a transaction identifier."
                )
        elif self.transaction_id is not None or self.contribution_date is None:
            raise ValueError(
                "Manual and opening-balance contributions require only a date."
            )
        return self


class ContributionResponse(GoalSchema):
    """Public contribution evidence without its ownership key."""

    id: UUID
    goal_id: UUID
    transaction_id: UUID | None
    amount: GoalMoney
    contribution_date: date
    source_type: ContributionSourceType
    note: str | None
    created_at: datetime
    updated_at: datetime


class ContributionListResponse(GoalSchema):
    items: tuple[ContributionResponse, ...]


class GoalProgressResponse(GoalSchema):
    goal_id: UUID
    currency: GoalCurrency
    target_amount: GoalMoney
    starting_amount: GoalMoney
    contribution_amount: GoalMoney
    current_amount: GoalMoney
    remaining_amount: GoalMoney
    funding_ratio: Decimal
    funding_percentage: Decimal
    months_remaining: int
    required_monthly_contribution: GoalMoney
    funding_state: GoalFundingState
    calculated_on: date


class PlanningProfileEvidenceResponse(GoalSchema):
    completion_status: ProfileCompletionStatus
    income_stability: str | None
    emergency_fund_target_months: Decimal | None
    updated_at: datetime


class PlanningFinancialEvidenceResponse(GoalSchema):
    liquid_balance: GoalMoney
    liability_account_count: int
    liability_payment_count: int
    outstanding_debt: GoalMoney
    monthly_debt_payment: GoalMoney
    source_last_updated_at: datetime | None


class PlanningBudgetEvidenceResponse(GoalSchema):
    active_budget_count: int
    budget_with_overall_limit_count: int
    total_overall_limit: GoalMoney
    source_last_updated_at: datetime | None


class SavingsCapacityPointResponse(GoalSchema):
    period_start: date
    protected_amount: GoalMoney
    expected_amount: GoalMoney
    upside_amount: GoalMoney


class SavingsCapacityResponse(GoalSchema):
    forecast_run_id: UUID
    currency: GoalCurrency
    policy_version: str
    protection_band: str
    reliability: str
    points: tuple[SavingsCapacityPointResponse, ...]
    protected_total: GoalMoney
    expected_total: GoalMoney
    upside_total: GoalMoney


class PlanningProvenanceResponse(GoalSchema):
    goal_ids: tuple[UUID, ...]
    contribution_count: int
    forecast_run_id: UUID | None
    source_last_updated_at: datetime | None


class GoalPlanningSnapshotResponse(GoalSchema):
    snapshot_id: str
    contract_version: str
    cutoff_at: datetime
    local_date: date
    timezone: str
    currency: GoalCurrency
    goals: tuple[GoalProgressResponse, ...]
    profile: PlanningProfileEvidenceResponse | None
    finances: PlanningFinancialEvidenceResponse
    budgets: PlanningBudgetEvidenceResponse
    savings_capacity: SavingsCapacityResponse | None
    warnings: tuple[PlanningSnapshotWarning, ...]
    provenance: PlanningProvenanceResponse
