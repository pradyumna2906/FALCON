"""Transactional email/password login and session issuance."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.auth.services import AuthenticationCryptography
from falcon_api.core.errors import ApplicationError
from falcon_api.models.auth import (
    RefreshSession,
    RefreshToken,
    UserCredential,
)
from falcon_api.models.enums import UserStatus
from falcon_api.models.user import User


_INVALID_CREDENTIALS_CODE: Final = "invalid_credentials"
_DUMMY_PASSWORD: Final = "falcon-dummy-login-password"


@dataclass(frozen=True, slots=True)
class LoginCommand:
    """Validated credentials submitted for authentication."""

    email: str
    password: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Credentials and metadata produced by successful login."""

    user_id: UUID
    session_id: UUID
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


class LoginService:
    """Authenticate credentials and issue one atomic session pair."""

    def __init__(
        self,
        *,
        cryptography: AuthenticationCryptography,
        refresh_lifetime: timedelta,
        clock: Clock | None = None,
    ) -> None:
        if refresh_lifetime <= timedelta(0):
            raise ValueError("Refresh-session lifetime must be positive.")

        self._cryptography = cryptography
        self._refresh_lifetime = refresh_lifetime
        self._clock = clock or SystemClock()
        self._dummy_password_hash = (
            cryptography.passwords.hash_password(_DUMMY_PASSWORD)
        )

    async def login(
        self,
        session: AsyncSession,
        command: LoginCommand,
    ) -> LoginResult:
        """Authenticate without revealing which credential check failed."""
        query_result = await session.execute(
            select(User, UserCredential)
            .join(
                UserCredential,
                UserCredential.user_id == User.id,
            )
            .where(User.email == command.email)
            .with_for_update()
        )
        account = query_result.one_or_none()

        encoded_hash = (
            account[1].password_hash
            if account is not None
            else self._dummy_password_hash
        )
        verified, replacement_hash = await asyncio.to_thread(
            self._cryptography.passwords.verify_and_update,
            command.password,
            encoded_hash,
        )

        if account is None:
            raise _invalid_credentials()

        user, credential = account

        if not verified or user.status != UserStatus.ACTIVE:
            raise _invalid_credentials()

        now = self._clock.now()

        if replacement_hash is not None:
            credential.password_hash = replacement_hash
            credential.password_changed_at = now
            credential.updated_at = now

        session_id = uuid4()
        family_id = uuid4()
        refresh_token = self._cryptography.generate_opaque_token()
        refresh_expires_at = now + self._refresh_lifetime

        refresh_session = RefreshSession(
            id=session_id,
            user_id=user.id,
            family_id=family_id,
            last_used_at=None,
            expires_at=refresh_expires_at,
            revoked_at=None,
            revocation_reason=None,
            created_at=now,
            updated_at=now,
        )
        stored_refresh_token = RefreshToken(
            id=uuid4(),
            session_id=session_id,
            token_hash=refresh_token.digest,
            used_at=None,
            created_at=now,
            updated_at=now,
        )

        session.add_all(
            [
                refresh_session,
                stored_refresh_token,
            ]
        )
        await session.flush()

        access_token = self._cryptography.access_tokens.create(
            user_id=user.id,
            session_id=session_id,
        )

        return LoginResult(
            user_id=user.id,
            session_id=session_id,
            access_token=access_token.value,
            access_token_expires_at=access_token.claims.expires_at,
            refresh_token=refresh_token.value,
            refresh_token_expires_at=refresh_expires_at,
        )


def _invalid_credentials() -> ApplicationError:
    return ApplicationError(
        code=_INVALID_CREDENTIALS_CODE,
        message="The email address or password is incorrect.",
        status_code=401,
    )
