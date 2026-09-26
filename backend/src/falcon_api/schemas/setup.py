"""Strict frontend setup contracts; owners are never client inputs."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from falcon_api.models.enums import LiabilitySubtype
from falcon_api.schemas.imports import ImportJobResponse
from falcon_api.schemas.ledger import AccountResponse

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=19, decimal_places=4)]
NonnegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=19, decimal_places=4)]


class SetupSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class AccountMetadataRequest(SetupSchema):
    name: Name
    institution_name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
        ]
        | None
    ) = None
    masked_reference: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
        ]
        | None
    ) = None


class AccountDetailResponse(AccountResponse):
    archived_at: datetime | None


class LiabilityRequest(SetupSchema):
    liability_subtype: LiabilitySubtype
    principal_amount: NonnegativeMoney | None = None
    outstanding_amount: NonnegativeMoney | None = None
    annual_interest_rate: (
        Annotated[Decimal, Field(ge=0, le=1, max_digits=10, decimal_places=6)] | None
    ) = None
    minimum_payment: NonnegativeMoney | None = None
    payment_due_day: Annotated[int, Field(ge=1, le=31)] | None = None
    start_date: date | None = None
    maturity_date: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        if (
            self.start_date
            and self.maturity_date
            and self.maturity_date < self.start_date
        ):
            raise ValueError("Maturity cannot precede start date.")
        return self


class LiabilityResponse(LiabilityRequest):
    id: UUID
    account_id: UUID
    created_at: datetime
    updated_at: datetime


class BudgetLimitRequest(SetupSchema):
    category_id: UUID
    limit_amount: PositiveMoney


class BudgetRequest(SetupSchema):
    name: Name
    period_start_date: date
    period_end_date: date
    currency: Currency
    overall_limit: PositiveMoney | None = None
    limits: Annotated[tuple[BudgetLimitRequest, ...], Field(max_length=100)] = ()

    @model_validator(mode="after")
    def validate_budget(self):
        if self.period_end_date < self.period_start_date:
            raise ValueError("Budget end cannot precede start.")
        if (self.period_end_date - self.period_start_date).days > 366:
            raise ValueError("Budget period cannot exceed 367 inclusive days.")
        if self.overall_limit is None and not self.limits:
            raise ValueError("At least one spending limit is required.")
        if len({item.category_id for item in self.limits}) != len(self.limits):
            raise ValueError("Budget categories must be unique.")
        return self


class BudgetResponse(BudgetRequest):
    id: UUID
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BudgetListResponse(SetupSchema):
    items: tuple[BudgetResponse, ...]
    has_more: bool


class ImportHistoryResponse(SetupSchema):
    items: tuple[ImportJobResponse, ...]
    has_more: bool


class PreferencesRequest(SetupSchema):
    display_name: Name | None = None
    timezone: Annotated[str, Field(min_length=1, max_length=64)]
    default_currency: Currency

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Timezone must be a valid IANA identifier.") from None
        return value
