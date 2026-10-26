"""Shared safe API error response schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

ErrorCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]
RequestId = Annotated[str, Field(min_length=1, max_length=64)]


class ValidationIssue(BaseModel):
    """Sanitized field-level validation feedback."""

    model_config = ConfigDict(frozen=True)

    field: str
    message: str


class ErrorDetail(BaseModel):
    """Stable machine-readable and user-safe failure details."""

    model_config = ConfigDict(frozen=True)

    code: ErrorCode
    message: str
    request_id: RequestId
    timestamp: datetime
    details: tuple[ValidationIssue, ...] | None = None


class ErrorResponse(BaseModel):
    """Common envelope returned for every API failure."""

    model_config = ConfigDict(frozen=True)

    error: ErrorDetail
