"""Real PostgreSQL authenticated-principal lifecycle tests."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from falcon_api.auth.login import LoginCommand, LoginService
from falcon_api.auth.principal import CurrentPrincipalService
from falcon_api.auth.registration import (
    RegistrationCommand,
    RegistrationService,
)
from falcon_api.auth.services import create_authentication_cryptography
from falcon_api.auth.session_lifecycle import SessionLifecycleService
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
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
_NOW = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
_PASSWORD = "Current-Principal-Password-2026!"


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


def test_postgresql_current_principal_lifecycle() -> None:
    """Resolve access before logout and reject it after revocation."""
    asyncio.run(
        _exercise_current_principal_lifecycle(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_current_principal_lifecycle() -> None:
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
    principal_service = CurrentPrincipalService(
        access_tokens=cryptography.access_tokens,
        clock=FixedClock(),
    )
    session_service = SessionLifecycleService(
        cryptography=cryptography,
        clock=FixedClock(),
    )

    email = f"phase-3-8-{uuid4().hex}@example.com"
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
                    display_name="Phase 3.8 Integration User",
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

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            principal = await principal_service.authenticate(
                session,
                token=login.access_token,
            )

        assert principal.user_id == user_id
        assert principal.session_id == login.session_id
        assert principal.email == email
        assert principal.display_name == "Phase 3.8 Integration User"
        assert principal.timezone == "Asia/Kolkata"
        assert principal.default_currency == "INR"

        async with transaction_scope(
            resources.session_factory,
        ) as session:
            await session_service.logout(
                session,
                token=login.refresh_token,
            )

        with pytest.raises(ApplicationError) as exc_info:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await principal_service.authenticate(
                    session,
                    token=login.access_token,
                )

        assert exc_info.value.code == "invalid_access_token"
        assert exc_info.value.status_code == 401
    finally:
        if user_id is not None:
            async with transaction_scope(
                resources.session_factory,
            ) as session:
                await session.execute(
                    delete(User).where(User.id == user_id)
                )

        await resources.dispose()
