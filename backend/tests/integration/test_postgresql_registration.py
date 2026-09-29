"""Real PostgreSQL registration and email-verification lifecycle tests."""

import asyncio
import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from falcon_api.auth.delivery import EncryptedDeliveryPayload
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


def integration_settings() -> Settings:
    """Load ignored local secrets with deterministic test behavior."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is at the reviewed migration head."""
    config = Config(str(_ALEMBIC_CONFIG))
    command.upgrade(config, "head")
    yield


def test_registration_resend_confirmation_and_replay_lifecycle() -> None:
    """Exercise the complete Phase 3.4 workflow against PostgreSQL."""
    asyncio.run(
        _exercise_registration_lifecycle(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_registration_lifecycle() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    cryptography = create_authentication_cryptography(settings)
    service = RegistrationService(
        cryptography=cryptography,
        verification_lifetime=timedelta(
            minutes=settings.auth_email_verification_lifetime_minutes
        ),
    )
    email = f"phase-3-4-{uuid4().hex}@falcon.test"
    user_id = None

    try:
        async with transaction_scope(
            resources.session_factory
        ) as session:
            result = await service.register(
                session,
                RegistrationCommand(
                    email=email,
                    password="correct horse battery staple",
                    display_name="Phase 3.4 User",
                    timezone="Asia/Kolkata",
                    default_currency="INR",
                ),
            )
            user_id = result.user_id

        async with transaction_scope(
            resources.session_factory
        ) as session:
            user = await session.scalar(
                select(User).where(User.id == user_id)
            )
            credential = await session.scalar(
                select(UserCredential).where(
                    UserCredential.user_id == user_id
                )
            )
            first_challenge = await session.scalar(
                select(AuthenticationChallenge).where(
                    AuthenticationChallenge.user_id == user_id,
                    AuthenticationChallenge.purpose
                    == AuthenticationChallengePurpose.EMAIL_VERIFICATION,
                    AuthenticationChallenge.consumed_at.is_(None),
                    AuthenticationChallenge.invalidated_at.is_(None),
                )
            )

            assert user is not None
            assert user.email == email
            assert user.email_verified_at is None
            assert credential is not None
            assert credential.password_hash.startswith("$argon2id$")
            assert first_challenge is not None

            first_delivery = await session.scalar(
                select(AuthenticationDelivery).where(
                    AuthenticationDelivery.challenge_id
                    == first_challenge.id
                )
            )

            assert first_delivery is not None
            assert email.encode() not in first_delivery.encrypted_payload

            first_message = (
                cryptography.deliveries.decrypt_email_verification(
                    EncryptedDeliveryPayload(
                        ciphertext=first_delivery.encrypted_payload,
                        key_id=first_delivery.encryption_key_id,
                    )
                )
            )

            assert first_message.email == email
            assert first_message.token.encode() not in (
                first_delivery.encrypted_payload
            )
            first_token = first_message.token
            first_challenge_id = first_challenge.id

        with pytest.raises(ApplicationError) as conflict_info:
            async with transaction_scope(
                resources.session_factory
            ) as session:
                await service.register(
                    session,
                    RegistrationCommand(
                        email=email,
                        password="another secure password",
                        display_name=None,
                        timezone="Asia/Kolkata",
                        default_currency="INR",
                    ),
                )

        assert conflict_info.value.code == "email_already_registered"

        async with transaction_scope(
            resources.session_factory
        ) as session:
            await service.request_email_verification(
                session,
                email=email,
            )

        async with transaction_scope(
            resources.session_factory
        ) as session:
            invalidated_first = await session.scalar(
                select(AuthenticationChallenge).where(
                    AuthenticationChallenge.id == first_challenge_id
                )
            )
            active_challenge = await session.scalar(
                select(AuthenticationChallenge).where(
                    AuthenticationChallenge.user_id == user_id,
                    AuthenticationChallenge.purpose
                    == AuthenticationChallengePurpose.EMAIL_VERIFICATION,
                    AuthenticationChallenge.consumed_at.is_(None),
                    AuthenticationChallenge.invalidated_at.is_(None),
                )
            )

            assert invalidated_first is not None
            assert invalidated_first.invalidated_at is not None
            assert active_challenge is not None
            assert active_challenge.id != first_challenge_id

            active_delivery = await session.scalar(
                select(AuthenticationDelivery).where(
                    AuthenticationDelivery.challenge_id
                    == active_challenge.id
                )
            )

            assert active_delivery is not None

            active_message = (
                cryptography.deliveries.decrypt_email_verification(
                    EncryptedDeliveryPayload(
                        ciphertext=active_delivery.encrypted_payload,
                        key_id=active_delivery.encryption_key_id,
                    )
                )
            )
            active_token = active_message.token

        with pytest.raises(ApplicationError) as replaced_info:
            async with transaction_scope(
                resources.session_factory
            ) as session:
                await service.confirm_email_verification(
                    session,
                    token=first_token,
                )

        assert replaced_info.value.code == "invalid_verification_token"

        async with transaction_scope(
            resources.session_factory
        ) as session:
            await service.confirm_email_verification(
                session,
                token=active_token,
            )

        async with transaction_scope(
            resources.session_factory
        ) as session:
            verified_user = await session.scalar(
                select(User).where(User.id == user_id)
            )
            consumed_challenge = await session.scalar(
                select(AuthenticationChallenge).where(
                    AuthenticationChallenge.id == active_challenge.id
                )
            )
            challenge_count = await session.scalar(
                select(func.count())
                .select_from(AuthenticationChallenge)
                .where(AuthenticationChallenge.user_id == user_id)
            )
            delivery_count = await session.scalar(
                select(func.count())
                .select_from(AuthenticationDelivery)
                .where(AuthenticationDelivery.user_id == user_id)
            )

            assert verified_user is not None
            assert verified_user.email_verified_at is not None
            assert consumed_challenge is not None
            assert consumed_challenge.consumed_at is not None
            assert challenge_count == 2
            assert delivery_count == 2

        with pytest.raises(ApplicationError) as replay_info:
            async with transaction_scope(
                resources.session_factory
            ) as session:
                await service.confirm_email_verification(
                    session,
                    token=active_token,
                )

        assert replay_info.value.code == "invalid_verification_token"

        async with transaction_scope(
            resources.session_factory
        ) as session:
            await service.request_email_verification(
                session,
                email="unknown-user@falcon.test",
            )

    finally:
        if user_id is not None:
            try:
                async with transaction_scope(
                    resources.session_factory
                ) as session:
                    user = await session.scalar(
                        select(User).where(User.id == user_id)
                    )

                    if user is not None:
                        await session.delete(user)
            finally:
                await resources.dispose()
        else:
            await resources.dispose()
