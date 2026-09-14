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

from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType


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
