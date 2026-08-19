"""Public financial-profile request and response schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class FinancialProfileSchema(BaseModel):
    """Strict immutable base for financial-profile API contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )


class FinancialProfilePutRequest(FinancialProfileSchema):
    """Replace the authenticated user's current planning context."""

    income_pattern: IncomePattern | None
    income_stability: IncomeStability | None
    has_household_responsibilities: bool
    dependant_count: int = Field(ge=0, le=50)
    emergency_fund_target_months: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("60"),
        max_digits=5,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def validate_household_context(self) -> "FinancialProfilePutRequest":
        """Prevent dependants without household responsibilities."""
        if (
            not self.has_household_responsibilities
            and self.dependant_count != 0
        ):
            raise ValueError(
                "Dependant count must be zero when household "
                "responsibilities are false."
            )

        return self


class FinancialProfileResponse(FinancialProfileSchema):
    """Return the authenticated user's current planning context."""

    id: UUID
    income_pattern: IncomePattern | None
    income_stability: IncomeStability | None
    has_household_responsibilities: bool
    dependant_count: int
    emergency_fund_target_months: Decimal | None
    completion_status: ProfileCompletionStatus
    created_at: datetime
    updated_at: datetime
