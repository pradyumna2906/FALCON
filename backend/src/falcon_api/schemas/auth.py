"""Public authentication request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from falcon_api.auth.email_identity import normalize_email_address


class AuthenticationSchema(BaseModel):
    """Strict immutable base for authentication API contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class RegistrationRequest(AuthenticationSchema):
    """Create one email/password FALCON account."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )
    timezone: str = Field(
        default="Asia/Kolkata",
        min_length=1,
        max_length=64,
    )
    default_currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Store only the canonical email identity."""
        return normalize_email_address(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(
        cls,
        value: str | None,
    ) -> str | None:
        """Trim optional presentation whitespace and reject blanks."""
        if value is None:
            return None

        normalized = value.strip()

        if not normalized:
            raise ValueError("Display name must not be blank.")

        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Accept only an installed IANA timezone identifier."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError(
                "Timezone must be a valid IANA identifier."
            ) from None

        return value


class RegisteredUserResponse(AuthenticationSchema):
    """Minimal identity returned after successful registration."""

    id: UUID
    email: str
    email_verified: Literal[False] = False


class LoginRequest(AuthenticationSchema):
    """Authenticate one normalized email/password identity."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize login lookups identically to registration."""
        return normalize_email_address(value)


class LoginResponse(AuthenticationSchema):
    """Return a short-lived access credential and expiry metadata."""

    access_token: str = Field(min_length=1)
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class EmailVerificationRequest(AuthenticationSchema):
    """Request a replacement verification message."""

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize resend lookups identically to registration."""
        return normalize_email_address(value)


class EmailVerificationConfirmation(AuthenticationSchema):
    """Consume one raw email-verification token."""

    token: str = Field(
        min_length=43,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

class PasswordResetRequest(AuthenticationSchema):
    """Request a password-reset message without account disclosure."""

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize password-reset lookups consistently."""
        return normalize_email_address(value)


class PasswordResetConfirmation(AuthenticationSchema):
    """Consume a password-reset token and replace the credential."""

    token: str = Field(
        min_length=43,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    new_password: str = Field(
        min_length=12,
        max_length=128,
    )
class CurrentUserResponse(AuthenticationSchema):
    """Return the authenticated user's non-sensitive account identity."""

    id: UUID
    email: str
    display_name: str | None
    timezone: str
    default_currency: str
    email_verified: bool


class GenericAcceptedResponse(AuthenticationSchema):
    """Enumeration-resistant response for message requests."""

    status: Literal["accepted"] = "accepted"
