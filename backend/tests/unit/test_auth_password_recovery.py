"""Unit contracts for transactional password recovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock
from falcon_api.auth.delivery import (
    AuthenticationDeliveryCipher,
    EncryptedDeliveryPayload,
)
from falcon_api.auth.opaque_tokens import hash_opaque_token
from falcon_api.auth.password_recovery import PasswordRecoveryService
from falcon_api.auth.passwords import PasswordService
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


_NOW = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
_RAW_TOKEN = "a" * 43
_NEW_PASSWORD = "New-Correct-Horse-Battery-Staple-2026!"
_NEW_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "c2FsdHNhbHRzYWx0c2FsdA$"
    "aGFzaGhhc2hoYXNoaGFzaGhhc2hoYXNoaGFzaA"
)


def _clock() -> Mock:
    clock = Mock(spec=Clock)
    clock.now.return_value = _NOW
    return clock


def _cryptography() -> AuthenticationCryptography:
    passwords = Mock(spec=PasswordService)
    passwords.hash_password.return_value = _NEW_PASSWORD_HASH

    return AuthenticationCryptography(
        passwords=cast(PasswordService, passwords),
        access_tokens=cast(Any, object()),
        deliveries=AuthenticationDeliveryCipher(
            encryption_key=Fernet.generate_key().decode("ascii"),
            key_id="phase-3-7-test-key",
        ),
        opaque_token_bytes=32,
    )


def _service(
    cryptography: AuthenticationCryptography,
) -> PasswordRecoveryService:
    return PasswordRecoveryService(
        cryptography=cryptography,
        reset_lifetime=timedelta(minutes=30),
        clock=cast(Clock, _clock()),
    )


def _session(*scalar_results: object) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = list(scalar_results)
    session.add_all = Mock()
    return session


def _user(
    *,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        status=status,
        display_name="Recovery User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW - timedelta(days=10),
        created_at=_NOW - timedelta(days=30),
        updated_at=_NOW - timedelta(days=10),
    )


def _challenge(
    user: User,
    *,
    consumed_at: datetime | None = None,
    invalidated_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> AuthenticationChallenge:
    return AuthenticationChallenge(
        id=uuid4(),
        user_id=user.id,
        purpose=AuthenticationChallengePurpose.PASSWORD_RESET,
        token_hash=hash_opaque_token(_RAW_TOKEN),
        expires_at=expires_at or (_NOW + timedelta(minutes=30)),
        consumed_at=consumed_at,
        invalidated_at=invalidated_at,
        created_at=_NOW - timedelta(minutes=1),
        updated_at=_NOW - timedelta(minutes=1),
    )


def _credential(user: User) -> UserCredential:
    return UserCredential(
        id=uuid4(),
        user_id=user.id,
        password_hash=(
            "$argon2id$v=19$m=65536,t=3,p=4$"
            "b2xkc2FsdG9sZHNhbHQ$"
            "b2xkaGFzaG9sZGhhc2hvbGRoYXNo"
        ),
        password_changed_at=_NOW - timedelta(days=30),
        created_at=_NOW - timedelta(days=30),
        updated_at=_NOW - timedelta(days=30),
    )


def test_password_recovery_requires_positive_lifetime() -> None:
    with pytest.raises(
        ValueError,
        match="Password-reset lifetime must be positive",
    ):
        PasswordRecoveryService(
            cryptography=_cryptography(),
            reset_lifetime=timedelta(0),
        )


@pytest.mark.parametrize(
    "user",
    [
        None,
        _user(status=UserStatus.DISABLED),
    ],
)
def test_reset_request_hides_ineligible_accounts(
    user: User | None,
) -> None:
    service = _service(_cryptography())
    session = _session(user)

    asyncio.run(
        service.request_password_reset(
            session,
            email="user@example.com",
        )
    )

    session.execute.assert_not_awaited()
    session.add_all.assert_not_called()
    session.flush.assert_not_awaited()


def test_reset_request_replaces_active_challenge_and_queues_delivery() -> None:
    cryptography = _cryptography()
    service = _service(cryptography)
    user = _user()
    session = _session(user)

    asyncio.run(
        service.request_password_reset(
            session,
            email=user.email,
        )
    )

    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()
    session.add_all.assert_called_once()

    challenge, delivery = session.add_all.call_args.args[0]

    assert isinstance(challenge, AuthenticationChallenge)
    assert isinstance(delivery, AuthenticationDelivery)
    assert challenge.user_id == user.id
    assert (
        challenge.purpose
        == AuthenticationChallengePurpose.PASSWORD_RESET
    )
    assert len(challenge.token_hash) == 64
    assert challenge.expires_at == _NOW + timedelta(minutes=30)
    assert challenge.consumed_at is None
    assert challenge.invalidated_at is None
    assert delivery.user_id == user.id
    assert delivery.challenge_id == challenge.id
    assert delivery.status == AuthenticationDeliveryStatus.PENDING

    decrypted = cryptography.deliveries.decrypt_password_reset(
        EncryptedDeliveryPayload(
            ciphertext=delivery.encrypted_payload,
            key_id=delivery.encryption_key_id,
        )
    )

    assert decrypted.email == user.email
    assert hash_opaque_token(decrypted.token) == challenge.token_hash


@pytest.mark.parametrize(
    ("challenge", "user"),
    [
        (None, None),
        (
            _challenge(
                _user(),
                consumed_at=_NOW - timedelta(seconds=1),
            ),
            None,
        ),
        (
            _challenge(
                _user(),
                invalidated_at=_NOW - timedelta(seconds=1),
            ),
            None,
        ),
        (
            _challenge(
                _user(),
                expires_at=_NOW,
            ),
            None,
        ),
    ],
)
def test_reset_confirmation_rejects_invalid_tokens(
    challenge: AuthenticationChallenge | None,
    user: User | None,
) -> None:
    service = _service(_cryptography())
    session = _session(challenge, user)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            service.confirm_password_reset(
                session,
                token=_RAW_TOKEN,
                new_password=_NEW_PASSWORD,
            )
        )

    assert exc_info.value.code == "invalid_password_reset_token"
    assert exc_info.value.status_code == 400
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "user",
    [
        None,
        _user(status=UserStatus.DISABLED),
    ],
)
def test_reset_confirmation_rejects_ineligible_users(
    user: User | None,
) -> None:
    source_user = _user()
    challenge = _challenge(source_user)
    service = _service(_cryptography())
    session = _session(challenge, user)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            service.confirm_password_reset(
                session,
                token=_RAW_TOKEN,
                new_password=_NEW_PASSWORD,
            )
        )

    assert exc_info.value.code == "invalid_password_reset_token"
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()


def test_reset_confirmation_rejects_missing_credential() -> None:
    user = _user()
    service = _service(_cryptography())
    session = _session(_challenge(user), user, None)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            service.confirm_password_reset(
                session,
                token=_RAW_TOKEN,
                new_password=_NEW_PASSWORD,
            )
        )

    assert exc_info.value.code == "invalid_password_reset_token"
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()


def test_reset_confirmation_changes_password_and_revokes_sessions() -> None:
    cryptography = _cryptography()
    service = _service(cryptography)
    user = _user()
    challenge = _challenge(user)
    credential = _credential(user)
    session = _session(challenge, user, credential)

    asyncio.run(
        service.confirm_password_reset(
            session,
            token=_RAW_TOKEN,
            new_password=_NEW_PASSWORD,
        )
    )

    password_service = cast(Mock, cryptography.passwords)
    password_service.hash_password.assert_called_once_with(_NEW_PASSWORD)

    assert challenge.consumed_at == _NOW
    assert challenge.updated_at == _NOW
    assert credential.password_hash == _NEW_PASSWORD_HASH
    assert credential.password_changed_at == _NOW
    assert credential.updated_at == _NOW
    assert user.updated_at == _NOW
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()
