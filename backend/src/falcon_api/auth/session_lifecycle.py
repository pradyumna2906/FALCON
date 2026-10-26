"""Refresh-token rotation, replay revocation, and logout workflows."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.auth.opaque_tokens import hash_opaque_token
from falcon_api.auth.services import AuthenticationCryptography
from falcon_api.core.errors import (
    ApplicationError,
    CommittedApplicationError,
)
from falcon_api.models.auth import RefreshSession, RefreshToken
from falcon_api.models.enums import UserStatus
from falcon_api.models.user import User


_INVALID_REFRESH_CODE: Final = "invalid_refresh_session"
_REPLAY_REVOCATION_REASON: Final = "refresh_token_reuse"
_LOGOUT_REVOCATION_REASON: Final = "logout"


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Credentials and metadata produced by successful rotation."""

    user_id: UUID
    session_id: UUID
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


class SessionLifecycleService:
    """Own refresh rotation, replay handling, and logout policy."""

    def __init__(
        self,
        *,
        cryptography: AuthenticationCryptography,
        clock: Clock | None = None,
    ) -> None:
        self._cryptography = cryptography
        self._clock = clock or SystemClock()

    async def refresh(
        self,
        session: AsyncSession,
        *,
        token: str,
    ) -> RefreshResult:
        """Rotate one valid refresh token exactly once."""
        now = self._clock.now()
        token_hash = hash_opaque_token(token)
        query_result = await session.execute(
            select(RefreshToken, RefreshSession, User)
            .join(
                RefreshSession,
                RefreshSession.id == RefreshToken.session_id,
            )
            .join(
                User,
                User.id == RefreshSession.user_id,
            )
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        state = query_result.one_or_none()

        if state is None:
            raise _invalid_refresh_session()

        stored_token, refresh_session, user = state

        if stored_token.used_at is not None:
            await session.execute(
                update(RefreshSession)
                .where(
                    RefreshSession.family_id
                    == refresh_session.family_id,
                    RefreshSession.revoked_at.is_(None),
                )
                .values(
                    revoked_at=now,
                    revocation_reason=_REPLAY_REVOCATION_REASON,
                    updated_at=now,
                )
            )
            await session.flush()
            raise _replayed_refresh_session()

        if (
            refresh_session.revoked_at is not None
            or refresh_session.expires_at <= now
            or user.status != UserStatus.ACTIVE
        ):
            raise _invalid_refresh_session()

        replacement = self._cryptography.generate_opaque_token()

        stored_token.used_at = now
        stored_token.updated_at = now
        refresh_session.last_used_at = now
        refresh_session.updated_at = now

        replacement_record = RefreshToken(
            id=uuid4(),
            session_id=refresh_session.id,
            token_hash=replacement.digest,
            used_at=None,
            created_at=now,
            updated_at=now,
        )
        session.add(replacement_record)
        await session.flush()

        access_token = self._cryptography.access_tokens.create(
            user_id=user.id,
            session_id=refresh_session.id,
        )

        return RefreshResult(
            user_id=user.id,
            session_id=refresh_session.id,
            access_token=access_token.value,
            access_token_expires_at=access_token.claims.expires_at,
            refresh_token=replacement.value,
            refresh_token_expires_at=refresh_session.expires_at,
        )

    async def logout(
        self,
        session: AsyncSession,
        *,
        token: str | None,
    ) -> None:
        """Revoke a resolvable refresh session without disclosing state."""
        if token is None:
            return

        now = self._clock.now()
        query_result = await session.execute(
            select(RefreshToken, RefreshSession)
            .join(
                RefreshSession,
                RefreshSession.id == RefreshToken.session_id,
            )
            .where(
                RefreshToken.token_hash == hash_opaque_token(token)
            )
            .with_for_update()
        )
        state = query_result.one_or_none()

        if state is None:
            return

        stored_token, refresh_session = state

        if stored_token.used_at is None:
            stored_token.used_at = now
            stored_token.updated_at = now

        if refresh_session.revoked_at is None:
            refresh_session.revoked_at = now
            refresh_session.revocation_reason = _LOGOUT_REVOCATION_REASON
            refresh_session.updated_at = now

        await session.flush()


def _invalid_refresh_session() -> ApplicationError:
    return ApplicationError(
        code=_INVALID_REFRESH_CODE,
        message="The refresh session is invalid or expired.",
        status_code=401,
    )


def _replayed_refresh_session() -> CommittedApplicationError:
    return CommittedApplicationError(
        code=_INVALID_REFRESH_CODE,
        message="The refresh session is invalid or expired.",
        status_code=401,
    )
