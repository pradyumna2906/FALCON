"""Real PostgreSQL owner and lifecycle tests for Phase 10 goals."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning import GoalCreateCommand, GoalService, GoalUpdateCommand
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType, UserStatus
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
_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


def integration_settings() -> Settings:
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def test_goal_lifecycle_is_owner_scoped_and_terminal() -> None:
    asyncio.run(_exercise_goal_lifecycle())


async def _exercise_goal_lifecycle() -> None:
    resources = create_database_resources(integration_settings())
    owner_id = uuid4()
    other_id = uuid4()
    service = GoalService(clock=FixedClock())
    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([_user(owner_id, "goal-owner"), _user(other_id, "other")])
        async with transaction_scope(resources.session_factory) as session:
            goal = await service.create(
                session,
                user_id=owner_id,
                default_currency="INR",
                trusted_timezone="Asia/Kolkata",
                command=GoalCreateCommand(
                    name="Education Fund",
                    goal_type=GoalType.EDUCATION,
                    target_amount=Decimal("200000.0000"),
                    starting_amount=Decimal("25000.0000"),
                    currency=None,
                    target_date=date(2028, 6, 1),
                    priority=GoalPriority.HIGH,
                    description="Semester fees",
                ),
            )
            goal_id = goal.id

        async with transaction_scope(resources.session_factory) as session:
            owner_goals = await service.list(
                session,
                user_id=owner_id,
                status=GoalStatus.ACTIVE,
                limit=10,
            )
            other_goals = await service.list(
                session,
                user_id=other_id,
                status=None,
                limit=10,
            )
            assert tuple(goal.id for goal in owner_goals) == (goal_id,)
            assert other_goals == ()
            with pytest.raises(ApplicationError) as hidden:
                await service.get(session, user_id=other_id, goal_id=goal_id)
            assert hidden.value.code == "goal_not_found"

        async with transaction_scope(resources.session_factory) as session:
            updated = await service.update(
                session,
                user_id=owner_id,
                goal_id=goal_id,
                trusted_timezone="Asia/Kolkata",
                command=GoalUpdateCommand(
                    fields=frozenset({"priority", "description"}),
                    priority=GoalPriority.CRITICAL,
                    description=None,
                ),
            )
            assert updated.priority is GoalPriority.CRITICAL
            assert updated.description is None

        async with transaction_scope(resources.session_factory) as session:
            completed = await service.complete(
                session,
                user_id=owner_id,
                goal_id=goal_id,
            )
            assert completed.status is GoalStatus.COMPLETED

        async with transaction_scope(resources.session_factory) as session:
            with pytest.raises(ApplicationError) as terminal:
                await service.cancel(
                    session,
                    user_id=owner_id,
                    goal_id=goal_id,
                )
            assert terminal.value.code == "goal_inactive"
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(
                delete(User).where(User.id.in_((owner_id, other_id)))
            )
        await resources.dispose()


def _user(user_id: UUID, label: str) -> User:
    return User(
        id=user_id,
        email=f"{label}-{uuid4().hex}@falcon.test",
        status=UserStatus.ACTIVE,
        display_name=label,
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
