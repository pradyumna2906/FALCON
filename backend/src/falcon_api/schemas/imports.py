"""Strict contracts for authenticated statement imports."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from falcon_api.models.enums import ImportDateOrder, ImportSourceType, ImportStatus
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


SupportedStatementSource = Literal[
    ImportSourceType.CSV,
    ImportSourceType.EXCEL,
    ImportSourceType.BANK_STATEMENT,
]
SafeFilename = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
SheetName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=31),
]


class ImportIssueCode(StrEnum):
    """Stable, non-sensitive reasons that an input row was rejected."""

    MISSING_DATE = "missing_date"
    INVALID_DATE = "invalid_date"
    FUTURE_DATE = "future_date"
    MISSING_AMOUNT = "missing_amount"
    INVALID_AMOUNT = "invalid_amount"
    INVALID_CURRENCY = "invalid_currency"
    ZERO_AMOUNT = "zero_amount"
    AMBIGUOUS_AMOUNT = "ambiguous_amount"
    MISSING_DESCRIPTION = "missing_description"
    INVALID_DESCRIPTION = "invalid_description"
    DESCRIPTION_TOO_LONG = "description_too_long"
    UNCACHED_FORMULA = "uncached_formula"
    DUPLICATE_TRANSACTION = "duplicate_transaction"


class ImportSchema(BaseModel):
    """Forbid undeclared values and freeze validated import data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )


class StatementImportOptions(ImportSchema):
    """User-controlled metadata accepted with one statement upload."""

    account_id: UUID
    source_type: SupportedStatementSource
    date_order: ImportDateOrder = ImportDateOrder.DAY_FIRST
    header_row: int = Field(default=1, ge=1, le=50)
    sheet_name: SheetName | None = None

    @field_validator("sheet_name", mode="before")
    @classmethod
    def normalize_blank_sheet_name(cls, value: object) -> object:
        """Treat a blank optional worksheet name as omitted."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_source_specific_options(self) -> "StatementImportOptions":
        """Only Excel input can select a worksheet."""
        if self.source_type != ImportSourceType.EXCEL and self.sheet_name:
            raise ValueError("sheet_name is available only for Excel imports.")
        return self


class ImportRowIssue(ImportSchema):
    """Expose a bounded row failure without echoing private source values."""

    row_number: int = Field(ge=1)
    code: ImportIssueCode
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]


class ImportJobResponse(ImportSchema):
    """Expose one user-owned import job without internal fingerprints."""

    id: UUID
    account_id: UUID
    source_type: SupportedStatementSource
    original_filename: SafeFilename
    status: ImportStatus
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    issues: tuple[ImportRowIssue, ...] = Field(max_length=100)
    issues_truncated: bool
    adapter_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] | None = None
    balance_reconciled: bool | None = None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("original_filename")
    @classmethod
    def validate_safe_filename(cls, value: str) -> str:
        """Keep paths and control characters outside public job metadata."""
        if (
            value in {".", ".."}
            or "/" in value
            or "\\" in value
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("original_filename must be a safe base name.")
        return value
