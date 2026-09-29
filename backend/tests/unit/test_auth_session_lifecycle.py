"""Tests for refresh rotation, replay revocation, and logout."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.opaque_tokens import hash_opaque_token
from falcon_api.auth.services import create_authentication_cryptography
from falcon_api.auth.session_lifecycle import SessionLifecycleService
from falcon_api.core.config import Settings
from falcon_api.core.errors import (
    ApplicationError,
    CommittedApplicationError,
)
from falcon_api.models.auth import RefreshSession, RefreshToken
from falcon_api.models.enums import UserStatus
from falcon_api.models.user import User


_NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)
_RAW_TOKEN = "R" * 43


class FixedClock:
    """Return one deterministic timestamp."""

    def now(self) -> datetime:
        return _NOW


@pytest.fixture
def cryptography():
    settings = Settings(
        _env_file=None,
        auth_signing_secret="x" * 48,
        auth_delivery_encryption_key=(
            Fernet.generate_key().decode("ascii")
        ),
        auth_delivery_encryption_key_id="test-key-v1",
    )

    return create_authentication_cryptography(
        settings,
        clock=FixedClock(),
    )


@pytest.fixture
def service(cryptography) -> SessionLifecycleService:
    return SessionLifecycleService(
        cryptography=cryptography,
        clock=FixedClock(),
    )


def _state(
    *,
    used: bool = False,
    revoked: bool = False,
    expired: bool = False,
    status: UserStatus = UserStatus.ACTIVE,
):
    user = User(
        id=uuid4(),
        email="user@example.com",
        status=status,
        display_name=None,
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=None,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW,
    )
    refresh_session = RefreshSession(
        id=uuid4(),
        user_id=user.id,
        family_id=uuid4(),
        last_used_at=None,
        expires_at=(
            _NOW - timedelta(seconds=1)
            if expired
            else _NOW + timedelta(days=7)
        ),
        revoked_at=_NOW if revoked else None,
        revocation_reason="test" if revoked else None,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW,
    )
    token = RefreshToken(
        id=uuid4(),
        session_id=refresh_session.id,
        token_hash=hash_opaque_token(_RAW_TOKEN),
        used_at=_NOW if used else None,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW,
    )

    return token, refresh_session, user


def _session(*, row) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    result = Mock()
    result.one_or_none.return_value = row
    session.execute.return_value = result
    return session


def test_refresh_rotates_token_and_issues_access(
    service: SessionLifecycleService,
    cryptography,
) -> None:
    token, refresh_session, user = _state()
    session = _session(row=(token, refresh_session, user))

    result = asyncio.run(
        service.refresh(session, token=_RAW_TOKEN)
    )

    assert result.user_id == user.id
    assert result.session_id == refresh_session.id
    assert result.refresh_token != _RAW_TOKEN
    assert result.refresh_token_expires_at == refresh_session.expires_at
    assert token.used_at == _NOW
    assert refresh_session.last_used_at == _NOW

    replacement = session.add.call_args.args[0]

    assert isinstance(replacement, RefreshToken)
    assert replacement.session_id == refresh_session.id
    assert replacement.token_hash == hash_opaque_token(
        result.refresh_token
    )
    assert replacement.used_at is None
    session.flush.assert_awaited_once_with()

    claims = cryptography.access_tokens.decode(result.access_token)

    assert claims.user_id == user.id
    assert claims.session_id == refresh_session.id


def test_refresh_replay_revokes_family_and_requires_commit(
    service: SessionLifecycleService,
) -> None:
    token, refresh_session, user = _state(used=True)
    first_result = Mock()
    first_result.one_or_none.return_value = (
        token,
        refresh_session,
        user,
    )
    second_result = Mock()
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    session.execute.side_effect = [first_result, second_result]

    with pytest.raises(CommittedApplicationError) as exc_info:
        asyncio.run(
            service.refresh(session, token=_RAW_TOKEN)
        )

    assert exc_info.value.code == "invalid_refresh_session"
    assert session.execute.await_count == 2
    session.flush.assert_awaited_once_with()
    session.add.assert_not_called()


@pytest.mark.parametrize(
    "state",
    [
        "missing",
        "revoked",
        "expired",
        "disabled",
    ],
)
def test_refresh_rejects_invalid_session_state(
    service: SessionLifecycleService,
    state: str,
) -> None:
    if state == "missing":
        row = None
    else:
        row = _state(
            revoked=state == "revoked",
            expired=state == "expired",
            status=(
                UserStatus.DISABLED
                if state == "disabled"
                else UserStatus.ACTIVE
            ),
        )

    session = _session(row=row)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            service.refresh(session, token=_RAW_TOKEN)
        )

    assert exc_info.value.code == "invalid_refresh_session"
    assert exc_info.value.status_code == 401
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def test_logout_revokes_session_and_consumes_active_token(
    service: SessionLifecycleService,
) -> None:
    token, refresh_session, _ = _state()
    session = _session(row=(token, refresh_session))

    asyncio.run(service.logout(session, token=_RAW_TOKEN))

    assert token.used_at == _NOW
    assert refresh_session.revoked_at == _NOW
    assert refresh_session.revocation_reason == "logout"
    session.flush.assert_awaited_once_with()


@pytest.mark.parametrize("token_state", ["missing_cookie", "unknown"])
def test_logout_is_idempotent_for_unresolved_session(
    service: SessionLifecycleService,
    token_state: str,
) -> None:
    session = _session(row=None)

    asyncio.run(
        service.logout(
            session,
            token=None if token_state == "missing_cookie" else _RAW_TOKEN,
        )
    )

    if token_state == "missing_cookie":
        session.execute.assert_not_awaited()
    else:
        session.execute.assert_awaited_once()

    session.flush.assert_not_awaited()
