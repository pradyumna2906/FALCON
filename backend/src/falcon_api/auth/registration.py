"""Transactional registration and email-verification workflows."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from falcon_api.auth.opaque_tokens import hash_opaque_token
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.auth.services import AuthenticationCryptography
from falcon_api.core.errors import ApplicationError
from falcon_api.models.auth import (
    AuthenticationChallenge,
    AuthenticationDelivery,
    UserCredential,
)
from falcon_api.models.enums import (
    AuthenticationChallengePurpose,
    AuthenticationDeliveryStatus,
    UserStatus,
)
from falcon_api.models.user import User


_EMAIL_CONFLICT_CODE: Final = "email_already_registered"
_INVALID_TOKEN_CODE: Final = "invalid_verification_token"
_USER_EMAIL_UNIQUE_CONSTRAINT: Final = "uq_users_email"


@dataclass(frozen=True, slots=True)
class RegistrationCommand:
    """Validated values required to create one account."""

    email: str
    password: str
    display_name: str | None
    timezone: str
    default_currency: str


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Minimal identity produced by successful registration."""

    user_id: UUID
    email: str


class RegistrationService:
    """Own registration and email-verification transaction policy."""

    def __init__(
        self,
        *,
        cryptography: AuthenticationCryptography,
        verification_lifetime: timedelta,
        clock: Clock | None = None,
    ) -> None:
        if verification_lifetime <= timedelta(0):
            raise ValueError(
                "Email-verification lifetime must be positive."
            )

        self._cryptography = cryptography
        self._verification_lifetime = verification_lifetime
        self._clock = clock or SystemClock()

    async def register(
        self,
        session: AsyncSession,
        command: RegistrationCommand,
    ) -> RegistrationResult:
        """Create an account and its verification delivery atomically."""
        existing_user_id = await session.scalar(
            select(User.id).where(User.email == command.email)
        )

        if existing_user_id is not None:
            raise _email_already_registered()

        now = self._clock.now()
        password_hash = await asyncio.to_thread(
            self._cryptography.passwords.hash_password,
            command.password,
        )
        user = User(
            id=uuid4(),
            email=command.email,
            status=UserStatus.ACTIVE,
            display_name=command.display_name,
            timezone=command.timezone,
            default_currency=command.default_currency,
            email_verified_at=None,
            created_at=now,
            updated_at=now,
        )
        credential = UserCredential(
            id=uuid4(),
            user_id=user.id,
            password_hash=password_hash,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
        )
        challenge, delivery = self._create_verification_delivery(
            user=user,
            now=now,
        )

        session.add_all(
            [
                user,
                credential,
                challenge,
                delivery,
            ]
        )

        try:
            await session.flush()
        except IntegrityError as exc:
            if _constraint_name(exc) == _USER_EMAIL_UNIQUE_CONSTRAINT:
                raise _email_already_registered() from None
            raise

        return RegistrationResult(
            user_id=user.id,
            email=user.email,
        )

    async def request_email_verification(
        self,
        session: AsyncSession,
        *,
        email: str,
    ) -> None:
        """Replace an eligible user's active verification challenge."""
        user = await session.scalar(
            select(User)
            .where(User.email == email)
            .with_for_update()
        )

        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or user.email_verified_at is not None
        ):
            return

        now = self._clock.now()

        await session.execute(
            update(AuthenticationChallenge)
            .where(
                AuthenticationChallenge.user_id == user.id,
                AuthenticationChallenge.purpose
                == AuthenticationChallengePurpose.EMAIL_VERIFICATION,
                AuthenticationChallenge.consumed_at.is_(None),
                AuthenticationChallenge.invalidated_at.is_(None),
            )
            .values(
                invalidated_at=now,
                updated_at=now,
            )
        )

        challenge, delivery = self._create_verification_delivery(
            user=user,
            now=now,
        )
        session.add_all([challenge, delivery])
        await session.flush()

    async def confirm_email_verification(
        self,
        session: AsyncSession,
        *,
        token: str,
    ) -> None:
        """Consume one valid verification token exactly once."""
        now = self._clock.now()
        token_hash = hash_opaque_token(token)

        challenge = await session.scalar(
            select(AuthenticationChallenge)
            .where(
                AuthenticationChallenge.token_hash == token_hash,
                AuthenticationChallenge.purpose
                == AuthenticationChallengePurpose.EMAIL_VERIFICATION,
            )
            .with_for_update()
        )

        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.invalidated_at is not None
            or challenge.expires_at <= now
        ):
            raise _invalid_verification_token()

        user = await session.scalar(
            select(User)
            .where(User.id == challenge.user_id)
            .with_for_update()
        )

        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or user.email_verified_at is not None
        ):
            raise _invalid_verification_token()

        challenge.consumed_at = now
        challenge.updated_at = now
        user.email_verified_at = now
        user.updated_at = now
        await session.flush()

    def _create_verification_delivery(
        self,
        *,
        user: User,
        now: datetime,
    ) -> tuple[AuthenticationChallenge, AuthenticationDelivery]:
        raw_token = self._cryptography.generate_opaque_token()
        encrypted = (
            self._cryptography.deliveries.encrypt_email_verification(
                email=user.email,
                token=raw_token.value,
            )
        )
        challenge = AuthenticationChallenge(
            id=uuid4(),
            user_id=user.id,
            purpose=AuthenticationChallengePurpose.EMAIL_VERIFICATION,
            token_hash=raw_token.digest,
            expires_at=now + self._verification_lifetime,
            consumed_at=None,
            invalidated_at=None,
            created_at=now,
            updated_at=now,
        )
        delivery = AuthenticationDelivery(
            id=uuid4(),
            user_id=user.id,
            challenge_id=challenge.id,
            encrypted_payload=encrypted.ciphertext,
            encryption_key_id=encrypted.key_id,
            status=AuthenticationDeliveryStatus.PENDING,
            attempt_count=0,
            available_at=now,
            processed_at=None,
            last_error_code=None,
            created_at=now,
            updated_at=now,
        )

        return challenge, delivery


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _email_already_registered() -> ApplicationError:
    return ApplicationError(
        code=_EMAIL_CONFLICT_CODE,
        message="An account with this email address already exists.",
        status_code=409,
    )


def _invalid_verification_token() -> ApplicationError:
    return ApplicationError(
        code=_INVALID_TOKEN_CODE,
        message="The email-verification token is invalid or expired.",
        status_code=400,
    )
