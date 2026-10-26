"""Tests for transactional registration and email verification."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth import (
    RegistrationCommand,
    RegistrationService,
    create_authentication_cryptography,
)
from falcon_api.auth.opaque_tokens import hash_opaque_token
from falcon_api.core.config import Settings
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


_NOW = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


@pytest.fixture
def service() -> RegistrationService:
    settings = Settings(
        _env_file=None,
        auth_signing_secret="x" * 48,
        auth_delivery_encryption_key=(
            Fernet.generate_key().decode("ascii")
        ),
        auth_delivery_encryption_key_id="test-key-v1",
    )

    return RegistrationService(
        cryptography=create_authentication_cryptography(
            settings,
            clock=FixedClock(),
        ),
        verification_lifetime=timedelta(minutes=30),
        clock=FixedClock(),
    )


@pytest.fixture
def command() -> RegistrationCommand:
    return RegistrationCommand(
        email="user@example.com",
        password="correct horse battery staple",
        display_name="Pradyumna",
        timezone="Asia/Kolkata",
        default_currency="INR",
    )


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add_all = Mock()
    return session


def test_registration_creates_complete_atomic_aggregate(
    service: RegistrationService,
    command: RegistrationCommand,
) -> None:
    session = _session()
    session.scalar.return_value = None

    result = asyncio.run(service.register(session, command))

    assert result.email == command.email
    assert result.user_id is not None

    added = session.add_all.call_args.args[0]
    user = next(item for item in added if isinstance(item, User))
    credential = next(
        item for item in added if isinstance(item, UserCredential)
    )
    challenge = next(
        item
        for item in added
        if isinstance(item, AuthenticationChallenge)
    )
    delivery = next(
        item
        for item in added
        if isinstance(item, AuthenticationDelivery)
    )

    assert user.id == result.user_id
    assert user.status is UserStatus.ACTIVE
    assert user.email_verified_at is None
    assert credential.user_id == user.id
    assert credential.password_hash.startswith("$argon2id$")
    assert challenge.user_id == user.id
    assert (
        challenge.purpose
        is AuthenticationChallengePurpose.EMAIL_VERIFICATION
    )
    assert challenge.expires_at == _NOW + timedelta(minutes=30)
    assert delivery.user_id == user.id
    assert delivery.challenge_id == challenge.id
    assert delivery.status is AuthenticationDeliveryStatus.PENDING
    assert delivery.encryption_key_id == "test-key-v1"
    assert command.email.encode() not in delivery.encrypted_payload
    session.flush.assert_awaited_once_with()


def test_registration_rejects_existing_email(
    service: RegistrationService,
    command: RegistrationCommand,
) -> None:
    session = _session()
    session.scalar.return_value = uuid4()

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(service.register(session, command))

    assert exc_info.value.code == "email_already_registered"
    assert exc_info.value.status_code == 409
    session.add_all.assert_not_called()


def test_registration_translates_email_uniqueness_race(
    service: RegistrationService,
    command: RegistrationCommand,
) -> None:
    session = _session()
    session.scalar.return_value = None
    original = Mock()
    original.diag.constraint_name = "uq_users_email"
    session.flush.side_effect = IntegrityError(
        "INSERT users",
        {},
        original,
    )

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(service.register(session, command))

    assert exc_info.value.code == "email_already_registered"


def test_registration_preserves_unrelated_integrity_error(
    service: RegistrationService,
    command: RegistrationCommand,
) -> None:
    session = _session()
    session.scalar.return_value = None
    original = Mock()
    original.diag.constraint_name = "ck_unrelated"
    failure = IntegrityError("INSERT users", {}, original)
    session.flush.side_effect = failure

    with pytest.raises(IntegrityError) as exc_info:
        asyncio.run(service.register(session, command))

    assert exc_info.value is failure


@pytest.mark.parametrize(
    ("status", "verified"),
    [
        (UserStatus.DISABLED, False),
        (UserStatus.ACTIVE, True),
    ],
)
def test_resend_is_generic_for_ineligible_user(
    service: RegistrationService,
    status: UserStatus,
    verified: bool,
) -> None:
    session = _session()
    session.scalar.return_value = User(
        id=uuid4(),
        email="user@example.com",
        status=status,
        display_name=None,
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW if verified else None,
        created_at=_NOW,
        updated_at=_NOW,
    )

    asyncio.run(
        service.request_email_verification(
            session,
            email="user@example.com",
        )
    )

    session.execute.assert_not_awaited()
    session.add_all.assert_not_called()


def test_resend_is_generic_for_unknown_email(
    service: RegistrationService,
) -> None:
    session = _session()
    session.scalar.return_value = None

    asyncio.run(
        service.request_email_verification(
            session,
            email="unknown@example.com",
        )
    )

    session.execute.assert_not_awaited()
    session.add_all.assert_not_called()


def test_resend_invalidates_and_replaces_active_challenge(
    service: RegistrationService,
) -> None:
    session = _session()
    user = User(
        id=uuid4(),
        email="user@example.com",
        status=UserStatus.ACTIVE,
        display_name=None,
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.scalar.return_value = user

    asyncio.run(
        service.request_email_verification(
            session,
            email=user.email,
        )
    )

    session.execute.assert_awaited_once()
    added = session.add_all.call_args.args[0]
    challenge = next(
        item
        for item in added
        if isinstance(item, AuthenticationChallenge)
    )
    delivery = next(
        item
        for item in added
        if isinstance(item, AuthenticationDelivery)
    )

    assert challenge.user_id == user.id
    assert delivery.challenge_id == challenge.id
    session.flush.assert_awaited_once_with()


@pytest.mark.parametrize(
    "challenge_state",
    [
        "missing",
        "consumed",
        "invalidated",
        "expired",
    ],
)
def test_confirmation_rejects_invalid_challenge_state(
    service: RegistrationService,
    challenge_state: str,
) -> None:
    session = _session()

    if challenge_state == "missing":
        session.scalar.return_value = None
    else:
        challenge = AuthenticationChallenge(
            id=uuid4(),
            user_id=uuid4(),
            purpose=AuthenticationChallengePurpose.EMAIL_VERIFICATION,
            token_hash=hash_opaque_token("A" * 43),
            expires_at=(
                _NOW - timedelta(seconds=1)
                if challenge_state == "expired"
                else _NOW + timedelta(minutes=30)
            ),
            consumed_at=_NOW if challenge_state == "consumed" else None,
            invalidated_at=(
                _NOW if challenge_state == "invalidated" else None
            ),
            created_at=_NOW - timedelta(minutes=1),
            updated_at=_NOW,
        )
        session.scalar.return_value = challenge

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            service.confirm_email_verification(
                session,
                token="A" * 43,
            )
        )

    assert exc_info.value.code == "invalid_verification_token"
    assert exc_info.value.status_code == 400


def test_confirmation_verifies_user_and_consumes_challenge(
    service: RegistrationService,
) -> None:
    session = _session()
    user_id = uuid4()
    challenge = AuthenticationChallenge(
        id=uuid4(),
        user_id=user_id,
        purpose=AuthenticationChallengePurpose.EMAIL_VERIFICATION,
        token_hash=hash_opaque_token("A" * 43),
        expires_at=_NOW + timedelta(minutes=30),
        consumed_at=None,
        invalidated_at=None,
        created_at=_NOW - timedelta(minutes=1),
        updated_at=_NOW,
    )
    user = User(
        id=user_id,
        email="user@example.com",
        status=UserStatus.ACTIVE,
        display_name=None,
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=None,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW,
    )
    session.scalar.side_effect = [challenge, user]

    asyncio.run(
        service.confirm_email_verification(
            session,
            token="A" * 43,
        )
    )

    assert challenge.consumed_at == _NOW
    assert user.email_verified_at == _NOW
    session.flush.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("user", "reason"),
    [
        (None, "missing"),
        (
            User(
                id=uuid4(),
                email="user@example.com",
                status=UserStatus.DISABLED,
                display_name=None,
                timezone="Asia/Kolkata",
                default_currency="INR",
                email_verified_at=None,
                created_at=_NOW,
                updated_at=_NOW,
            ),
            "disabled",
        ),
    ],
)
def test_confirmation_rejects_ineligible_user(
    service: RegistrationService,
    user: User | None,
    reason: str,
) -> None:
    session = _session()
    challenge = AuthenticationChallenge(
        id=uuid4(),
        user_id=uuid4(),
        purpose=AuthenticationChallengePurpose.EMAIL_VERIFICATION,
        token_hash=hash_opaque_token("A" * 43),
        expires_at=_NOW + timedelta(minutes=30),
        consumed_at=None,
        invalidated_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.scalar.side_effect = [challenge, user]

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            service.confirm_email_verification(
                session,
                token="A" * 43,
            )
        )

    assert reason
    assert exc_info.value.code == "invalid_verification_token"
