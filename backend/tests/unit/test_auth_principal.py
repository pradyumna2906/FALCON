"""Unit contracts for authenticated-principal resolution."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.access_tokens import (
    AccessTokenClaims,
    AccessTokenService,
)
from falcon_api.auth.clock import Clock
from falcon_api.auth.errors import InvalidAccessTokenError
from falcon_api.auth.principal import CurrentPrincipalService
from falcon_api.core.errors import ApplicationError
from falcon_api.models.auth import RefreshSession
from falcon_api.models.enums import UserStatus
from falcon_api.models.user import User


_NOW = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)
_TOKEN = "signed-access-token"


def _clock() -> Mock:
    clock = Mock(spec=Clock)
    clock.now.return_value = _NOW
    return clock


def _claims(
    *,
    user_id=None,
    session_id=None,
) -> AccessTokenClaims:
    return AccessTokenClaims(
        user_id=user_id or uuid4(),
        session_id=session_id or uuid4(),
        token_id=uuid4(),
        issued_at=_NOW - timedelta(minutes=1),
        not_before=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=14),
    )


def _user(
    user_id,
    *,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    return User(
        id=user_id,
        email="user@example.com",
        status=status,
        display_name="Authenticated User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW - timedelta(days=1),
        created_at=_NOW - timedelta(days=30),
        updated_at=_NOW - timedelta(days=1),
    )


def _refresh_session(
    user_id,
    session_id,
    *,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> RefreshSession:
    return RefreshSession(
        id=session_id,
        user_id=user_id,
        family_id=uuid4(),
        last_used_at=None,
        expires_at=expires_at or (_NOW + timedelta(days=7)),
        revoked_at=revoked_at,
        revocation_reason=(
            "logout" if revoked_at is not None else None
        ),
        created_at=_NOW - timedelta(minutes=5),
        updated_at=_NOW - timedelta(minutes=5),
    )


def _service(
    access_tokens: Mock,
) -> CurrentPrincipalService:
    return CurrentPrincipalService(
        access_tokens=access_tokens,
        clock=_clock(),
    )


def _session(row) -> AsyncMock:
    result = Mock()
    result.one_or_none.return_value = row

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    return session


def test_authenticate_rejects_invalid_signed_token() -> None:
    access_tokens = Mock(spec=AccessTokenService)
    access_tokens.decode.side_effect = InvalidAccessTokenError(
        "Invalid access token."
    )
    session = _session(None)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            _service(access_tokens).authenticate(
                session,
                token=_TOKEN,
            )
        )

    assert exc_info.value.code == "invalid_access_token"
    assert exc_info.value.status_code == 401
    session.execute.assert_not_awaited()


def test_authenticate_rejects_missing_database_identity() -> None:
    access_tokens = Mock(spec=AccessTokenService)
    access_tokens.decode.return_value = _claims()
    session = _session(None)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            _service(access_tokens).authenticate(
                session,
                token=_TOKEN,
            )
        )

    assert exc_info.value.code == "invalid_access_token"
    session.execute.assert_awaited_once()


@pytest.mark.parametrize(
    ("status", "revoked_at", "expires_at"),
    [
        (
            UserStatus.DISABLED,
            None,
            _NOW + timedelta(days=7),
        ),
        (
            UserStatus.ACTIVE,
            _NOW - timedelta(seconds=1),
            _NOW + timedelta(days=7),
        ),
        (
            UserStatus.ACTIVE,
            None,
            _NOW,
        ),
    ],
)
def test_authenticate_rejects_inactive_principal_state(
    status: UserStatus,
    revoked_at: datetime | None,
    expires_at: datetime,
) -> None:
    user_id = uuid4()
    session_id = uuid4()
    access_tokens = Mock(spec=AccessTokenService)
    access_tokens.decode.return_value = _claims(
        user_id=user_id,
        session_id=session_id,
    )
    user = _user(user_id, status=status)
    refresh_session = _refresh_session(
        user_id,
        session_id,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )
    session = _session((user, refresh_session))

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            _service(access_tokens).authenticate(
                session,
                token=_TOKEN,
            )
        )

    assert exc_info.value.code == "invalid_access_token"


def test_authenticate_returns_non_sensitive_principal() -> None:
    user_id = uuid4()
    session_id = uuid4()
    access_tokens = Mock(spec=AccessTokenService)
    access_tokens.decode.return_value = _claims(
        user_id=user_id,
        session_id=session_id,
    )
    user = _user(user_id)
    refresh_session = _refresh_session(user_id, session_id)
    session = _session((user, refresh_session))

    principal = asyncio.run(
        _service(access_tokens).authenticate(
            session,
            token=_TOKEN,
        )
    )

    assert principal.user_id == user_id
    assert principal.session_id == session_id
    assert principal.email == "user@example.com"
    assert principal.display_name == "Authenticated User"
    assert principal.timezone == "Asia/Kolkata"
    assert principal.default_currency == "INR"
    assert principal.email_verified_at == (
        _NOW - timedelta(days=1)
    )
    access_tokens.decode.assert_called_once_with(_TOKEN)
