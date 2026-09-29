"""Real PostgreSQL password-recovery lifecycle tests."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select

from falcon_api.auth.delivery import EncryptedDeliveryPayload
from falcon_api.auth.login import LoginCommand, LoginService
from falcon_api.auth.password_recovery import PasswordRecoveryService
from falcon_api.auth.registration import (
    RegistrationCommand,
    RegistrationService,
)
from falcon_api.auth.services import create_authentication_cryptography
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.auth import (
    AuthenticationChallenge,
    AuthenticationDelivery,
    RefreshSession,
    UserCredential,
)
from falcon_api.models.enums import AuthenticationChallengePurpose
from falcon_api.models.user import User


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_NOW = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)
_OLD_PASSWORD = "Old-Correct-Horse-Battery-Staple-2026!"
_NEW_PASSWORD = "New-Correct-Horse-Battery-Staple-2026!"


class FixedClock:
    """Return one deterministic authentication timestamp."""

    def now(self) -> datetime:
        return _NOW


def integration_settings() -> Settings:
    """Load ignored local secrets for PostgreSQL integration tests."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is at the current migration head."""
    config = Config(str(_ALEMBIC_CONFIG))
    command.upgrade(config, "head")
    yield


def test_postgresql_password_recovery_lifecycle() -> None:
    """Verify secure password recovery against real PostgreSQL."""
    asyncio.run(
        _exercise_password_recovery_lifecycle(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_password_recovery_lifecycle() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    cryptography = create_authentication_cryptography(
        settings,
        clock=FixedClock(),
    )
    registration_service = RegistrationService(
        cryptography=cryptography,
        verification_lifetime=timedelta(minutes=30),
        clock=FixedClock(),
    )
    login_service = LoginService(
        cryptography=cryptography,
        refresh_lifetime=timedelta(days=7),
        clock=FixedClock(),
    )
    recovery_service = PasswordRecoveryService(
        cryptography=cryptography,
        reset_lifetime=timedelta(minutes=30),
        clock=FixedClock(),
    )

    email = f"phase-3-7-{uuid4().hex}@example.com"
    user_id = None
    original_session_id = None
    raw_reset_token = None

    try:
        async with transaction_scope(
            resources.session_factory,
        ) as session:
            registered = await registration_service.register(
                session,
                RegistrationCommand(
                    email=email,
                    password=_OLD_PASSWORD,
                    display_name="Phase 3.7 Integration User",
                    timezone="Asia/Kolkata",
                    default_currency="INR",
                ),
            )
            user_id = registered.user_id

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            initial_login = await login_service.login(
                session,
                LoginCommand(
                    email=email,
                    password=_OLD_PASSWORD,
                ),
            )
            original_session_id = initial_login.session_id

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            await recovery_service.request_password_reset(
                session,
                email=email,
            )

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            challenge = await session.scalar(
                select(AuthenticationChallenge)
                .where(
                    AuthenticationChallenge.user_id == user_id,
                    AuthenticationChallenge.purpose
                    == AuthenticationChallengePurpose.PASSWORD_RESET,
                    AuthenticationChallenge.consumed_at.is_(None),
                    AuthenticationChallenge.invalidated_at.is_(None),
                )
                .order_by(AuthenticationChallenge.created_at.desc())
            )

            assert challenge is not None
            assert challenge.expires_at == (
                _NOW + timedelta(minutes=30)
            )

            delivery = await session.scalar(
                select(AuthenticationDelivery).where(
                    AuthenticationDelivery.challenge_id == challenge.id
                )
            )

            assert delivery is not None
            assert _OLD_PASSWORD.encode() not in delivery.encrypted_payload
            assert _NEW_PASSWORD.encode() not in delivery.encrypted_payload

            decrypted = cryptography.deliveries.decrypt_password_reset(
                EncryptedDeliveryPayload(
                    ciphertext=delivery.encrypted_payload,
                    key_id=delivery.encryption_key_id,
                )
            )
            raw_reset_token = decrypted.token

            assert decrypted.email == email
            assert raw_reset_token not in challenge.token_hash

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            await recovery_service.confirm_password_reset(
                session,
                token=raw_reset_token,
                new_password=_NEW_PASSWORD,
            )

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            challenge = await session.scalar(
                select(AuthenticationChallenge).where(
                    AuthenticationChallenge.user_id == user_id,
                    AuthenticationChallenge.purpose
                    == AuthenticationChallengePurpose.PASSWORD_RESET,
                )
            )
            credential = await session.scalar(
                select(UserCredential).where(
                    UserCredential.user_id == user_id
                )
            )
            original_session = await session.scalar(
                select(RefreshSession).where(
                    RefreshSession.id == original_session_id
                )
            )

            assert challenge is not None
            assert challenge.consumed_at == _NOW
            assert challenge.invalidated_at is None

            assert credential is not None
            assert credential.password_changed_at == _NOW
            assert credential.password_hash.startswith("$argon2id$")
            assert _OLD_PASSWORD not in credential.password_hash
            assert _NEW_PASSWORD not in credential.password_hash

            assert original_session is not None
            assert original_session.revoked_at == _NOW
            assert original_session.revocation_reason == "password_reset"

        with pytest.raises(ApplicationError) as replay_error:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await recovery_service.confirm_password_reset(
                    session,
                    token=raw_reset_token,
                    new_password=_NEW_PASSWORD,
                )

        assert replay_error.value.code == "invalid_password_reset_token"

        with pytest.raises(ApplicationError) as old_login_error:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await login_service.login(
                    session,
                    LoginCommand(
                        email=email,
                        password=_OLD_PASSWORD,
                    ),
                )

        assert old_login_error.value.code == "invalid_credentials"

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            replacement_login = await login_service.login(
                session,
                LoginCommand(
                    email=email,
                    password=_NEW_PASSWORD,
                ),
            )

        assert replacement_login.user_id == user_id
        assert replacement_login.session_id != original_session_id

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            await recovery_service.request_password_reset(
                session,
                email=f"unknown-{uuid4().hex}@example.com",
            )
    finally:
        if user_id is not None:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await session.execute(
                    delete(User).where(User.id == user_id)
                )

        await resources.dispose()
