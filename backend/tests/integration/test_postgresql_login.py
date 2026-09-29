"""Real PostgreSQL login and initial-session lifecycle tests."""

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

from falcon_api.auth.login import LoginCommand, LoginService
from falcon_api.auth.opaque_tokens import hash_opaque_token
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
    RefreshSession,
    RefreshToken,
    UserCredential,
)
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
_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
_PASSWORD = "correct horse battery staple"


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


def test_postgresql_login_and_session_issuance_lifecycle() -> None:
    """Verify login persistence and failure behavior against PostgreSQL."""
    asyncio.run(
        _exercise_login_lifecycle(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_login_lifecycle() -> None:
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
    email = f"phase-3-5-{uuid4().hex}@example.com"
    user_id = None

    try:
        async with transaction_scope(
            resources.session_factory,
        ) as session:
            registered = await registration_service.register(
                session,
                RegistrationCommand(
                    email=email,
                    password=_PASSWORD,
                    display_name="Phase 3.5 Integration User",
                    timezone="Asia/Kolkata",
                    default_currency="INR",
                ),
            )
            user_id = registered.user_id

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            login = await login_service.login(
                session,
                LoginCommand(
                    email=email,
                    password=_PASSWORD,
                ),
            )

        claims = cryptography.access_tokens.decode(login.access_token)

        assert claims.user_id == user_id
        assert claims.session_id == login.session_id
        assert login.access_token_expires_at == (
            _NOW + timedelta(minutes=15)
        )
        assert login.refresh_token_expires_at == (
            _NOW + timedelta(days=7)
        )

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            refresh_session = await session.scalar(
                select(RefreshSession).where(
                    RefreshSession.id == login.session_id
                )
            )
            refresh_token = await session.scalar(
                select(RefreshToken).where(
                    RefreshToken.session_id == login.session_id
                )
            )
            credential = await session.scalar(
                select(UserCredential).where(
                    UserCredential.user_id == user_id
                )
            )

            assert refresh_session is not None
            assert refresh_session.user_id == user_id
            assert refresh_session.expires_at == (
                _NOW + timedelta(days=7)
            )
            assert refresh_session.revoked_at is None

            assert refresh_token is not None
            assert refresh_token.token_hash == hash_opaque_token(
                login.refresh_token
            )
            assert login.refresh_token not in refresh_token.token_hash
            assert refresh_token.used_at is None

            assert credential is not None
            assert credential.password_hash.startswith("$argon2id$")
            assert _PASSWORD not in credential.password_hash

        with pytest.raises(ApplicationError) as exc_info:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await login_service.login(
                    session,
                    LoginCommand(
                        email=email,
                        password="incorrect password value",
                    ),
                )

        assert exc_info.value.code == "invalid_credentials"

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            session_count = await session.scalar(
                select(RefreshSession)
                .where(RefreshSession.user_id == user_id)
                .with_only_columns(
                    RefreshSession.id,
                )
            )

            assert session_count == login.session_id

        with pytest.raises(ApplicationError) as unknown_exc:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await login_service.login(
                    session,
                    LoginCommand(
                        email=f"unknown-{uuid4().hex}@example.com",
                        password=_PASSWORD,
                    ),
                )

        assert unknown_exc.value.code == "invalid_credentials"
    finally:
        if user_id is not None:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await session.execute(
                    delete(User).where(User.id == user_id)
                )

        await resources.dispose()
