"""Tests for secure login and initial session issuance."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.login import (
    LoginCommand,
    LoginService,
)
from falcon_api.auth.opaque_tokens import hash_opaque_token
from falcon_api.auth.services import (
    AuthenticationCryptography,
    create_authentication_cryptography,
)
from falcon_api.core.config import Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.models.auth import (
    RefreshSession,
    RefreshToken,
    UserCredential,
)
from falcon_api.models.enums import UserStatus
from falcon_api.models.user import User


_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
_PASSWORD = "correct horse battery staple"


class FixedClock:
    """Return one deterministic authentication timestamp."""

    def now(self) -> datetime:
        return _NOW


@pytest.fixture
def cryptography() -> AuthenticationCryptography:
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
def service(
    cryptography: AuthenticationCryptography,
) -> LoginService:
    return LoginService(
        cryptography=cryptography,
        refresh_lifetime=timedelta(days=7),
        clock=FixedClock(),
    )


def _user(
    *,
    status: UserStatus = UserStatus.ACTIVE,
    verified: bool = False,
) -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        status=status,
        display_name="Pradyumna",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW if verified else None,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW,
    )


def _credential(
    cryptography: AuthenticationCryptography,
    *,
    user: User,
) -> UserCredential:
    return UserCredential(
        id=uuid4(),
        user_id=user.id,
        password_hash=cryptography.passwords.hash_password(_PASSWORD),
        password_changed_at=_NOW - timedelta(days=1),
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW - timedelta(days=1),
    )


def _session(
    *,
    account: tuple[User, UserCredential] | None,
) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add_all = Mock()
    result = Mock()
    result.one_or_none.return_value = account
    session.execute.return_value = result
    return session


def test_login_creates_session_refresh_digest_and_access_token(
    service: LoginService,
    cryptography: AuthenticationCryptography,
) -> None:
    user = _user()
    credential = _credential(cryptography, user=user)
    session = _session(account=(user, credential))

    result = asyncio.run(
        service.login(
            session,
            LoginCommand(
                email=user.email,
                password=_PASSWORD,
            ),
        )
    )

    assert result.user_id == user.id
    assert result.refresh_token_expires_at == (
        _NOW + timedelta(days=7)
    )

    added = session.add_all.call_args.args[0]
    refresh_session = next(
        item
        for item in added
        if isinstance(item, RefreshSession)
    )
    refresh_token = next(
        item
        for item in added
        if isinstance(item, RefreshToken)
    )

    assert refresh_session.id == result.session_id
    assert refresh_session.user_id == user.id
    assert refresh_session.expires_at == result.refresh_token_expires_at
    assert refresh_session.revoked_at is None
    assert refresh_token.session_id == result.session_id
    assert refresh_token.token_hash == hash_opaque_token(
        result.refresh_token
    )
    assert result.refresh_token not in refresh_token.token_hash
    assert refresh_token.used_at is None
    session.flush.assert_awaited_once_with()

    claims = cryptography.access_tokens.decode(result.access_token)

    assert claims.user_id == user.id
    assert claims.session_id == result.session_id
    assert claims.expires_at == result.access_token_expires_at


@pytest.mark.parametrize(
    "account_state",
    [
        "unknown",
        "wrong_password",
        "disabled",
    ],
)
def test_login_uses_one_public_failure_for_invalid_credentials(
    service: LoginService,
    cryptography: AuthenticationCryptography,
    account_state: str,
) -> None:
    if account_state == "unknown":
        account = None
        password = _PASSWORD
    else:
        user = _user(
            status=(
                UserStatus.DISABLED
                if account_state == "disabled"
                else UserStatus.ACTIVE
            )
        )
        credential = _credential(cryptography, user=user)
        account = (user, credential)
        password = (
            "incorrect password value"
            if account_state == "wrong_password"
            else _PASSWORD
        )

    session = _session(account=account)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            service.login(
                session,
                LoginCommand(
                    email="user@example.com",
                    password=password,
                ),
            )
        )

    assert exc_info.value.code == "invalid_credentials"
    assert exc_info.value.status_code == 401
    assert exc_info.value.public_message == (
        "The email address or password is incorrect."
    )
    session.add_all.assert_not_called()
    session.flush.assert_not_awaited()


def test_active_unverified_user_can_login(
    service: LoginService,
    cryptography: AuthenticationCryptography,
) -> None:
    user = _user(verified=False)
    credential = _credential(cryptography, user=user)
    session = _session(account=(user, credential))

    result = asyncio.run(
        service.login(
            session,
            LoginCommand(
                email=user.email,
                password=_PASSWORD,
            ),
        )
    )

    assert result.user_id == user.id
    session.flush.assert_awaited_once_with()


def test_login_replaces_obsolete_password_hash(
    cryptography: AuthenticationCryptography,
) -> None:
    passwords = Mock()
    passwords.hash_password.return_value = "$argon2id$dummy"
    passwords.verify_and_update.return_value = (
        True,
        "$argon2id$replacement",
    )

    mocked_cryptography = AuthenticationCryptography(
        passwords=passwords,
        access_tokens=cryptography.access_tokens,
        deliveries=cryptography.deliveries,
        opaque_token_bytes=cryptography.opaque_token_bytes,
    )
    service = LoginService(
        cryptography=mocked_cryptography,
        refresh_lifetime=timedelta(days=7),
        clock=FixedClock(),
    )
    user = _user()
    credential = UserCredential(
        id=uuid4(),
        user_id=user.id,
        password_hash="$argon2id$obsolete",
        password_changed_at=_NOW - timedelta(days=2),
        created_at=_NOW - timedelta(days=2),
        updated_at=_NOW - timedelta(days=2),
    )
    session = _session(account=(user, credential))

    asyncio.run(
        service.login(
            session,
            LoginCommand(
                email=user.email,
                password=_PASSWORD,
            ),
        )
    )

    passwords.verify_and_update.assert_called_once_with(
        _PASSWORD,
        "$argon2id$obsolete",
    )
    assert credential.password_hash == "$argon2id$replacement"
    assert credential.password_changed_at == _NOW
    assert credential.updated_at == _NOW


def test_login_rejects_non_positive_refresh_lifetime(
    cryptography: AuthenticationCryptography,
) -> None:
    with pytest.raises(
        ValueError,
        match="Refresh-session lifetime must be positive",
    ):
        LoginService(
            cryptography=cryptography,
            refresh_lifetime=timedelta(0),
        )
