"""Transactional password-recovery workflows."""

import asyncio
from datetime import datetime, timedelta
from typing import Final
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.auth.opaque_tokens import hash_opaque_token
from falcon_api.auth.services import AuthenticationCryptography
from falcon_api.core.errors import ApplicationError
from falcon_api.models.auth import (
    AuthenticationChallenge,
    AuthenticationDelivery,
    RefreshSession,
    UserCredential,
)
from falcon_api.models.enums import (
    AuthenticationChallengePurpose,
    AuthenticationDeliveryStatus,
    UserStatus,
)
from falcon_api.models.user import User


_INVALID_RESET_TOKEN_CODE: Final = "invalid_password_reset_token"
_PASSWORD_RESET_REVOCATION_REASON: Final = "password_reset"


class PasswordRecoveryService:
    """Own password-reset request and confirmation transaction policy."""

    def __init__(
        self,
        *,
        cryptography: AuthenticationCryptography,
        reset_lifetime: timedelta,
        clock: Clock | None = None,
    ) -> None:
        if reset_lifetime <= timedelta(0):
            raise ValueError("Password-reset lifetime must be positive.")

        self._cryptography = cryptography
        self._reset_lifetime = reset_lifetime
        self._clock = clock or SystemClock()

    async def request_password_reset(
        self,
        session: AsyncSession,
        *,
        email: str,
    ) -> None:
        """Queue an eligible reset without disclosing account existence."""
        user = await session.scalar(
            select(User)
            .where(User.email == email)
            .with_for_update()
        )

        if user is None or user.status != UserStatus.ACTIVE:
            return

        now = self._clock.now()

        await session.execute(
            update(AuthenticationChallenge)
            .where(
                AuthenticationChallenge.user_id == user.id,
                AuthenticationChallenge.purpose
                == AuthenticationChallengePurpose.PASSWORD_RESET,
                AuthenticationChallenge.consumed_at.is_(None),
                AuthenticationChallenge.invalidated_at.is_(None),
            )
            .values(
                invalidated_at=now,
                updated_at=now,
            )
        )

        challenge, delivery = self._create_reset_delivery(
            user=user,
            now=now,
        )
        session.add_all([challenge, delivery])
        await session.flush()

    async def confirm_password_reset(
        self,
        session: AsyncSession,
        *,
        token: str,
        new_password: str,
    ) -> None:
        """Consume one reset token, replace the password and revoke sessions."""
        now = self._clock.now()
        token_hash = hash_opaque_token(token)

        challenge = await session.scalar(
            select(AuthenticationChallenge)
            .where(
                AuthenticationChallenge.token_hash == token_hash,
                AuthenticationChallenge.purpose
                == AuthenticationChallengePurpose.PASSWORD_RESET,
            )
            .with_for_update()
        )

        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.invalidated_at is not None
            or challenge.expires_at <= now
        ):
            raise _invalid_password_reset_token()

        user = await session.scalar(
            select(User)
            .where(User.id == challenge.user_id)
            .with_for_update()
        )

        if user is None or user.status != UserStatus.ACTIVE:
            raise _invalid_password_reset_token()

        credential = await session.scalar(
            select(UserCredential)
            .where(UserCredential.user_id == user.id)
            .with_for_update()
        )

        if credential is None:
            raise _invalid_password_reset_token()

        password_hash = await asyncio.to_thread(
            self._cryptography.passwords.hash_password,
            new_password,
        )

        challenge.consumed_at = now
        challenge.updated_at = now
        credential.password_hash = password_hash
        credential.password_changed_at = now
        credential.updated_at = now
        user.updated_at = now

        await session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=now,
                revocation_reason=_PASSWORD_RESET_REVOCATION_REASON,
                updated_at=now,
            )
        )

        await session.flush()

    def _create_reset_delivery(
        self,
        *,
        user: User,
        now: datetime,
    ) -> tuple[AuthenticationChallenge, AuthenticationDelivery]:
        """Create one hashed challenge and encrypted delivery record."""
        raw_token = self._cryptography.generate_opaque_token()
        encrypted = self._cryptography.deliveries.encrypt_password_reset(
            email=user.email,
            token=raw_token.value,
        )
        challenge = AuthenticationChallenge(
            id=uuid4(),
            user_id=user.id,
            purpose=AuthenticationChallengePurpose.PASSWORD_RESET,
            token_hash=raw_token.digest,
            expires_at=now + self._reset_lifetime,
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


def _invalid_password_reset_token() -> ApplicationError:
    """Return the single public reset-token failure."""
    return ApplicationError(
        code=_INVALID_RESET_TOKEN_CODE,
        message="The password-reset token is invalid or expired.",
        status_code=400,
    )
