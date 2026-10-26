"""Strict public contracts for ledger setup resources."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from falcon_api.classification.taxonomy import ClassificationSubcategoryCode
from falcon_api.models.enums import AccountType, CategoryKind
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


AccountName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
InstitutionName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
MaskedReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$"),
]
OpeningBalance = Annotated[
    Decimal,
    Field(max_digits=19, decimal_places=4),
]


class LedgerSchema(BaseModel):
    """Forbid undeclared fields and freeze validated ledger data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )


class AccountCreateRequest(LedgerSchema):
    """Provision one account owned by the authenticated user."""

    name: AccountName
    account_type: AccountType
    institution_name: InstitutionName | None = None
    masked_reference: MaskedReference | None = None
    currency: CurrencyCode | None = None
    opening_balance: OpeningBalance = Decimal("0")
    opening_balance_date: date

    @field_validator("institution_name", "masked_reference", mode="before")
    @classmethod
    def normalize_blank_optional_text(cls, value: object) -> object:
        """Treat omitted and blank optional display values equivalently."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        """Persist ISO-style currency identifiers in canonical uppercase."""
        return value.upper() if value is not None else None


class AccountResponse(LedgerSchema):
    """Expose one active account without its ownership key."""

    id: UUID
    name: AccountName
    account_type: AccountType
    institution_name: InstitutionName | None
    masked_reference: MaskedReference | None
    currency: CurrencyCode
    opening_balance: OpeningBalance
    opening_balance_date: date
    created_at: datetime
    updated_at: datetime


class AccountListResponse(LedgerSchema):
    """Return all active accounts owned by the principal."""

    items: tuple[AccountResponse, ...]


class CategoryResponse(LedgerSchema):
    """Expose an active category available to the principal."""

    id: UUID
    name: str
    classification_code: ClassificationSubcategoryCode | None
    kind: CategoryKind
    parent_id: UUID | None
    is_system: bool
    display_order: int


class CategoryListResponse(LedgerSchema):
    """Return system and private categories available to the principal."""

    items: tuple[CategoryResponse, ...]
