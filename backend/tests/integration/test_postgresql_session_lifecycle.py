"""PostgreSQL refresh rotation, replay, and logout lifecycle tests."""

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
from falcon_api.auth.registration import (
    RegistrationCommand,
    RegistrationService,
)
from falcon_api.auth.services import create_authentication_cryptography
from falcon_api.auth.session_lifecycle import SessionLifecycleService
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import (
    ApplicationError,
    CommittedApplicationError,
)
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.auth import RefreshSession, RefreshToken
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
_NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)
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
    """Ensure PostgreSQL is at the current migration head."""
    config = Config(str(_ALEMBIC_CONFIG))
    command.upgrade(config, "head")
    yield


def test_postgresql_refresh_replay_and_logout_lifecycle() -> None:
    """Verify rotation and committed family revocation in PostgreSQL."""
    asyncio.run(
        _exercise_session_lifecycle(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_session_lifecycle() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    cryptography = create_authentication_cryptography(
        settings,
        clock=FixedClock(),
    )
    registration = RegistrationService(
        cryptography=cryptography,
        verification_lifetime=timedelta(minutes=30),
        clock=FixedClock(),
    )
    login_service = LoginService(
        cryptography=cryptography,
        refresh_lifetime=timedelta(days=7),
        clock=FixedClock(),
    )
    lifecycle = SessionLifecycleService(
        cryptography=cryptography,
        clock=FixedClock(),
    )
    email = f"phase-3-6-{uuid4().hex}@example.com"
    user_id = None

    try:
        async with transaction_scope(
            resources.session_factory,
        ) as session:
            registered = await registration.register(
                session,
                RegistrationCommand(
                    email=email,
                    password=_PASSWORD,
                    display_name="Phase 3.6 Integration User",
                    timezone="Asia/Kolkata",
                    default_currency="INR",
                ),
            )
            user_id = registered.user_id

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            first_login = await login_service.login(
                session,
                LoginCommand(
                    email=email,
                    password=_PASSWORD,
                ),
            )

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            rotated = await lifecycle.refresh(
                session,
                token=first_login.refresh_token,
            )

        assert rotated.session_id == first_login.session_id
        assert rotated.refresh_token != first_login.refresh_token

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            tokens = (
                await session.scalars(
                    select(RefreshToken)
                    .where(
                        RefreshToken.session_id
                        == first_login.session_id
                    )
                    .order_by(RefreshToken.created_at)
                )
            ).all()

            assert len(tokens) == 2
            assert tokens[0].used_at == _NOW
            assert tokens[1].used_at is None

        with pytest.raises(CommittedApplicationError):
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await lifecycle.refresh(
                    session,
                    token=first_login.refresh_token,
                )

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            replayed_session = await session.get(
                RefreshSession,
                first_login.session_id,
            )

            assert replayed_session is not None
            assert replayed_session.revoked_at == _NOW
            assert replayed_session.revocation_reason == (
                "refresh_token_reuse"
            )

        with pytest.raises(ApplicationError) as revoked_exc:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await lifecycle.refresh(
                    session,
                    token=rotated.refresh_token,
                )

        assert revoked_exc.value.code == "invalid_refresh_session"

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            second_login = await login_service.login(
                session,
                LoginCommand(
                    email=email,
                    password=_PASSWORD,
                ),
            )

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            await lifecycle.logout(
                session,
                token=second_login.refresh_token,
            )

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            logged_out_session = await session.get(
                RefreshSession,
                second_login.session_id,
            )
            logged_out_token = await session.scalar(
                select(RefreshToken).where(
                    RefreshToken.session_id
                    == second_login.session_id
                )
            )

            assert logged_out_session is not None
            assert logged_out_session.revoked_at == _NOW
            assert logged_out_session.revocation_reason == "logout"
            assert logged_out_token is not None
            assert logged_out_token.used_at == _NOW
    finally:
        if user_id is not None:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await session.execute(
                    delete(User).where(User.id == user_id)
                )

        await resources.dispose()
