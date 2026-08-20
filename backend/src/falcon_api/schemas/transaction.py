"""Strict public contracts for transaction management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from falcon_api.models.enums import (
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


TransactionDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
MerchantName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
TransactionAmount = Annotated[
    Decimal,
    Field(gt=Decimal("0"), max_digits=19, decimal_places=4),
]
ManualTransactionType = Literal[
    TransactionType.INCOME,
    TransactionType.EXPENSE,
]


class TransactionSchema(BaseModel):
    """Forbid undeclared fields and freeze validated transaction data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )


class ManualTransactionWrite(TransactionSchema):
    """Values accepted when a user creates or replaces a manual entry."""

    account_id: UUID
    category_id: UUID | None = None
    transaction_type: ManualTransactionType
    amount: TransactionAmount
    transaction_date: date
    description: TransactionDescription
    merchant_name: MerchantName | None = None

    @field_validator("merchant_name", mode="before")
    @classmethod
    def normalize_blank_merchant(cls, value: object) -> object:
        """Treat an omitted merchant and a blank merchant equivalently."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ManualTransactionCreateRequest(ManualTransactionWrite):
    """Create one authenticated user's manual income or expense."""


class ManualTransactionReplaceRequest(ManualTransactionWrite):
    """Completely replace the mutable values of one manual entry."""


class TransferCreateRequest(TransactionSchema):
    """Create the two ledger entries of one user-owned internal transfer."""

    source_account_id: UUID
    destination_account_id: UUID
    amount: TransactionAmount
    transaction_date: date
    description: TransactionDescription

    @model_validator(mode="after")
    def validate_distinct_accounts(self) -> "TransferCreateRequest":
        """A transfer must move money between two different accounts."""
        if self.source_account_id == self.destination_account_id:
            raise ValueError(
                "Source and destination accounts must be different."
            )
        return self


class TransactionResponse(TransactionSchema):
    """Expose one transaction without ownership or deduplication internals."""

    id: UUID
    account_id: UUID
    category_id: UUID | None
    transaction_type: TransactionType
    amount: TransactionAmount
    transaction_date: date
    description: TransactionDescription
    merchant_name: MerchantName | None
    source_type: TransactionSourceType
    status: TransactionStatus
    is_user_modified: bool
    created_at: datetime
    updated_at: datetime


class TransferResponse(TransactionSchema):
    """Return the paired entries created for one internal transfer."""

    id: UUID
    debit: TransactionResponse
    credit: TransactionResponse


class TransactionListQuery(TransactionSchema):
    """Validated filters for a stable user-scoped transaction timeline."""

    account_id: UUID | None = None
    category_id: UUID | None = None
    transaction_type: TransactionType | None = None
    status: TransactionStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    cursor: Annotated[
        str | None,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=512,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] = None
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_date_window(self) -> "TransactionListQuery":
        """Reject an inverted inclusive transaction-date range."""
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to must not be earlier than date_from.")
        return self


class TransactionPageResponse(TransactionSchema):
    """Return one stable page and an opaque continuation cursor."""

    items: tuple[TransactionResponse, ...]
    next_cursor: str | None
