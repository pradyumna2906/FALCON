"""Real PostgreSQL financial-profile lifecycle and isolation tests."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.main import create_app
from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
    UserStatus,
)
from falcon_api.models.user import FinancialProfile, User
from falcon_api.profile import (
    FinancialProfileCommand,
    FinancialProfileRepository,
    FinancialProfileService,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_NOW = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
_PASSWORD = "Financial-Profile-Password-2026!"


class FixedClock:
    """Return one deterministic profile timestamp."""

    def now(self) -> datetime:
        return _NOW


class CoordinatedRepository(FinancialProfileRepository):
    """Synchronize absent-row reads to exercise the unique-key race."""

    def __init__(self, barrier: asyncio.Barrier) -> None:
        self._barrier = barrier

    async def get_by_user_id(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        for_update: bool = False,
    ) -> FinancialProfile | None:
        profile = await super().get_by_user_id(
            session,
            user_id=user_id,
            for_update=for_update,
        )
        if for_update and profile is None:
            await self._barrier.wait()
        return profile


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
    """Ensure profile tests run against the reviewed migration head."""
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def _command(
    *,
    income_pattern: IncomePattern | None,
    income_stability: IncomeStability | None,
    dependant_count: int,
) -> FinancialProfileCommand:
    return FinancialProfileCommand(
        income_pattern=income_pattern,
        income_stability=income_stability,
        has_household_responsibilities=dependant_count > 0,
        dependant_count=dependant_count,
        emergency_fund_target_months=Decimal("6.00"),
    )


def _user(*, email_prefix: str) -> User:
    return User(
        id=uuid4(),
        email=f"{email_prefix}-{uuid4().hex}@falcon.test",
        status=UserStatus.ACTIVE,
        display_name="Profile Integration User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


async def _delete_users(resources, *user_ids: UUID) -> None:
    async with transaction_scope(resources.session_factory) as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))


def test_postgresql_profile_lifecycle_isolation_and_rollback() -> None:
    """Exercise draft, replacement, ownership, uniqueness, and rollback."""
    asyncio.run(
        _exercise_profile_lifecycle(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_profile_lifecycle() -> None:
    resources = create_database_resources(integration_settings())
    service = FinancialProfileService(clock=FixedClock())
    owner = _user(email_prefix="profile-owner")
    other = _user(email_prefix="profile-other")
    draft_command = _command(
        income_pattern=None,
        income_stability=IncomeStability.VARIABLE,
        dependant_count=0,
    )
    complete_command = _command(
        income_pattern=IncomePattern.MIXED,
        income_stability=IncomeStability.STABLE,
        dependant_count=2,
    )

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, other])

        async with transaction_scope(resources.session_factory) as session:
            with pytest.raises(ApplicationError) as missing_info:
                await service.get(session, user_id=owner.id)
        assert missing_info.value.code == "profile_not_found"

        async with transaction_scope(resources.session_factory) as session:
            created = await service.put(
                session,
                user_id=owner.id,
                command=draft_command,
            )
        assert created.created is True
        assert created.profile.user_id == owner.id
        assert created.profile.completion_status is (
            ProfileCompletionStatus.DRAFT
        )

        async with transaction_scope(resources.session_factory) as session:
            stored_draft = await service.get(session, user_id=owner.id)
        assert stored_draft.id == created.profile.id
        assert stored_draft.income_pattern is None

        async with transaction_scope(resources.session_factory) as session:
            replaced = await service.put(
                session,
                user_id=owner.id,
                command=complete_command,
            )
        assert replaced.created is False
        assert replaced.profile.id == created.profile.id
        assert replaced.profile.completion_status is (
            ProfileCompletionStatus.COMPLETE
        )

        async with transaction_scope(resources.session_factory) as session:
            profile_count = await session.scalar(
                select(func.count())
                .select_from(FinancialProfile)
                .where(FinancialProfile.user_id == owner.id)
            )
        assert profile_count == 1

        async with transaction_scope(resources.session_factory) as session:
            with pytest.raises(ApplicationError) as isolation_info:
                await service.get(session, user_id=other.id)
        assert isolation_info.value.code == "profile_not_found"

        with pytest.raises(RuntimeError, match="force profile rollback"):
            async with transaction_scope(
                resources.session_factory
            ) as session:
                await service.put(
                    session,
                    user_id=owner.id,
                    command=draft_command,
                )
                raise RuntimeError("force profile rollback")

        async with transaction_scope(resources.session_factory) as session:
            after_rollback = await service.get(session, user_id=owner.id)
        assert after_rollback.income_pattern == IncomePattern.MIXED
        assert after_rollback.completion_status == (
            ProfileCompletionStatus.COMPLETE
        )

        duplicate = FinancialProfile(
            id=uuid4(),
            user_id=owner.id,
            income_pattern=None,
            income_stability=None,
            has_household_responsibilities=False,
            dependant_count=0,
            emergency_fund_target_months=None,
            completion_status=ProfileCompletionStatus.DRAFT,
            created_at=_NOW,
            updated_at=_NOW,
        )
        with pytest.raises(IntegrityError) as duplicate_info:
            async with transaction_scope(
                resources.session_factory
            ) as session:
                session.add(duplicate)
                await session.flush()

        diagnostic = getattr(duplicate_info.value.orig, "diag", None)
        assert getattr(diagnostic, "constraint_name", None) == (
            "uq_financial_profiles_user_id"
        )
    finally:
        await _delete_users(resources, owner.id, other.id)
        await resources.dispose()


def test_postgresql_concurrent_first_update_converges_to_one_profile() -> None:
    """Exercise the savepoint recovery path with two real connections."""
    asyncio.run(
        _exercise_concurrent_first_update(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_concurrent_first_update() -> None:
    resources = create_database_resources(integration_settings())
    owner = _user(email_prefix="profile-race")
    service = FinancialProfileService(
        repository=CoordinatedRepository(asyncio.Barrier(2)),
        clock=FixedClock(),
    )
    commands = (
        _command(
            income_pattern=IncomePattern.SALARIED,
            income_stability=IncomeStability.STABLE,
            dependant_count=1,
        ),
        _command(
            income_pattern=IncomePattern.SELF_EMPLOYED,
            income_stability=IncomeStability.VARIABLE,
            dependant_count=3,
        ),
    )

    async def update_profile(command_value):
        async with transaction_scope(
            resources.session_factory
        ) as session:
            return await service.put(
                session,
                user_id=owner.id,
                command=command_value,
            )

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add(owner)
        results = await asyncio.gather(
            *(update_profile(value) for value in commands)
        )
        assert sorted(result.created for result in results) == [False, True]

        async with transaction_scope(resources.session_factory) as session:
            profiles = (
                await session.scalars(
                    select(FinancialProfile).where(
                        FinancialProfile.user_id == owner.id
                    )
                )
            ).all()
        assert len(profiles) == 1
        assert profiles[0].completion_status == (
            ProfileCompletionStatus.COMPLETE
        )
        assert profiles[0].income_pattern in {
            IncomePattern.SALARIED,
            IncomePattern.SELF_EMPLOYED,
        }
    finally:
        await _delete_users(resources, owner.id)
        await resources.dispose()


def test_authenticated_profile_api_isolates_users_in_postgresql() -> None:
    """Exercise registration, login, profile PUT, and isolated GET."""
    settings = integration_settings()
    emails = (
        f"profile-api-a-{uuid4().hex}@example.com",
        f"profile-api-b-{uuid4().hex}@example.com",
    )
    user_ids: list[UUID] = []

    def register_and_login(client: TestClient, email: str) -> str:
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": _PASSWORD,
                "timezone": "Asia/Kolkata",
                "default_currency": "INR",
            },
        )
        assert registration.status_code == 201, registration.text
        user_ids.append(UUID(registration.json()["id"]))
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _PASSWORD},
        )
        assert login.status_code == 200
        return login.json()["access_token"]

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            first_token = register_and_login(client, emails[0])
            second_token = register_and_login(client, emails[1])
            payload = {
                "income_pattern": "salaried",
                "income_stability": "stable",
                "has_household_responsibilities": True,
                "dependant_count": 2,
                "emergency_fund_target_months": "6.00",
            }
            created = client.put(
                "/api/v1/profile",
                headers={"Authorization": f"Bearer {first_token}"},
                json=payload,
            )
            assert created.status_code == 201
            assert created.json()["completion_status"] == "complete"
            assert "user_id" not in created.json()

            retrieved = client.get(
                "/api/v1/profile",
                headers={"Authorization": f"Bearer {first_token}"},
            )
            assert retrieved.status_code == 200
            assert retrieved.json()["id"] == created.json()["id"]

            isolated = client.get(
                "/api/v1/profile",
                headers={"Authorization": f"Bearer {second_token}"},
            )
            assert isolated.status_code == 404
            assert isolated.json()["error"]["code"] == (
                "profile_not_found"
            )
    finally:
        if user_ids:
            resources = create_database_resources(settings)

            async def cleanup() -> None:
                await _delete_users(resources, *user_ids)
                await resources.dispose()

            asyncio.run(
                cleanup(),
                loop_factory=asyncio.SelectorEventLoop,
            )
