"""Resolution of authenticated users from bearer access tokens."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.access_tokens import AccessTokenService
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.auth.errors import InvalidAccessTokenError
from falcon_api.core.errors import ApplicationError
from falcon_api.models.auth import RefreshSession
from falcon_api.models.enums import UserStatus
from falcon_api.models.user import User


_INVALID_ACCESS_CODE: Final = "invalid_access_token"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Trusted non-sensitive identity resolved from an access token."""

    user_id: UUID
    session_id: UUID
    email: str
    display_name: str | None
    timezone: str
    default_currency: str
    email_verified_at: datetime | None


class CurrentPrincipalService:
    """Validate bearer credentials against cryptography and persistence."""

    def __init__(
        self,
        *,
        access_tokens: AccessTokenService,
        clock: Clock | None = None,
    ) -> None:
        self._access_tokens = access_tokens
        self._clock = clock or SystemClock()

    async def authenticate(
        self,
        session: AsyncSession,
        *,
        token: str,
    ) -> AuthenticatedPrincipal:
        """Resolve one active user and refresh-session principal."""
        try:
            claims = self._access_tokens.decode(token)
        except InvalidAccessTokenError:
            raise _invalid_access_token() from None

        result = await session.execute(
            select(User, RefreshSession)
            .join(
                RefreshSession,
                RefreshSession.user_id == User.id,
            )
            .where(
                User.id == claims.user_id,
                RefreshSession.id == claims.session_id,
            )
        )
        row = result.one_or_none()

        if row is None:
            raise _invalid_access_token()

        user, refresh_session = row
        now = self._clock.now()

        if (
            user.status != UserStatus.ACTIVE
            or refresh_session.revoked_at is not None
            or refresh_session.expires_at <= now
        ):
            raise _invalid_access_token()

        return AuthenticatedPrincipal(
            user_id=user.id,
            session_id=refresh_session.id,
            email=user.email,
            display_name=user.display_name,
            timezone=user.timezone,
            default_currency=user.default_currency,
            email_verified_at=user.email_verified_at,
        )


def _invalid_access_token() -> ApplicationError:
    """Return one uniform public authorization failure."""
    return ApplicationError(
        code=_INVALID_ACCESS_CODE,
        message="The access token is invalid or expired.",
        status_code=401,
    )
