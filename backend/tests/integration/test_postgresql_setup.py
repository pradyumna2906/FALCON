"""Exercise setup persistence, ownership, archival, and rollback on PostgreSQL."""

import asyncio
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import AccountType, CategoryKind, UserStatus
from falcon_api.models.user import User
from falcon_api.schemas.setup import (
    AccountMetadataRequest,
    BudgetRequest,
    LiabilityRequest,
    PreferencesRequest,
)
from falcon_api.setup.service import SetupService
from sqlalchemy import delete

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]
ROOT = Path(__file__).resolve().parents[3]


def test_setup_lifecycle_ownership_and_atomic_replacement():
    command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
    asyncio.run(_exercise_setup(), loop_factory=asyncio.SelectorEventLoop)


async def _exercise_setup():
    resources = create_database_resources(
        Settings(
            _env_file=ROOT / ".env",
            env=AppEnvironment.TEST,
        )
    )
    service = SetupService()
    now = datetime.now(UTC)
    owner, other, account_id, category_id = (uuid4() for _ in range(4))
    payload = BudgetRequest(
        name="September",
        period_start_date=date(2026, 9, 1),
        period_end_date=date(2026, 9, 30),
        currency="INR",
        limits=({"category_id": category_id, "limit_amount": "123.4567"},),
    )
    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all(
                [
                    User(
                        id=identifier,
                        email=f"setup-{identifier}@example.com",
                        status=UserStatus.ACTIVE,
                        timezone="UTC",
                        default_currency="INR",
                        email_verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    for identifier in (owner, other)
                ]
            )
            await session.flush()
            session.add(
                Account(
                    id=account_id,
                    user_id=owner,
                    name="Debt",
                    account_type=AccountType.LOAN,
                    currency="INR",
                    opening_balance=Decimal(0),
                    opening_balance_date=date(2026, 9, 1),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                Category(
                    id=category_id,
                    user_id=owner,
                    name="Food",
                    normalized_name="food",
                    kind=CategoryKind.EXPENSE,
                    is_system=False,
                    display_order=0,
                    created_at=now,
                    updated_at=now,
                )
            )

        async with transaction_scope(resources.session_factory) as session:
            budget = await service.put_budget(session, owner, payload)
            budget_id = budget.id
            assert budget.limits[0].limit_amount == Decimal("123.4567")
            await service.update_account(
                session, owner, account_id, AccountMetadataRequest(name="Loan")
            )
            await service.put_liability(
                session,
                owner,
                account_id,
                LiabilityRequest(
                    liability_subtype="loan",
                    outstanding_amount="765.4321",
                    annual_interest_rate="0.125678",
                ),
            )
            await service.preferences(
                session,
                owner,
                PreferencesRequest(
                    display_name="Owner",
                    timezone="Asia/Kolkata",
                    default_currency="USD",
                ),
            )

        async with transaction_scope(resources.session_factory) as session:
            assert (
                await service.get_account(session, owner, account_id)
            ).name == "Loan"
            assert (
                await service.get_account(session, owner, account_id)
            ).currency == "INR"
            assert (
                await service.get_liability(session, owner, account_id)
            ).annual_interest_rate == Decimal("0.125678")
            assert (await service.preferences(session, owner)).default_currency == "USD"
            assert (
                await service.repository.budgets(
                    session, other, limit=10, offset=0, archived=False
                )
                == ()
            )
            assert (
                await service.repository.imports(session, other, limit=10, offset=0)
                == ()
            )
            for method, identifier in (
                (service.get_budget, budget_id),
                (service.get_account, account_id),
                (service.get_liability, account_id),
            ):
                with pytest.raises(ApplicationError) as error:
                    await method(session, other, identifier)
                assert error.value.status_code == 404
            with pytest.raises(ApplicationError) as error:
                await service.put_budget(session, other, payload)
            assert error.value.status_code == 404
            with pytest.raises(ApplicationError) as error:
                await service.put_budget(session, owner, payload)
            assert error.value.status_code == 409

        replacement = payload.model_copy(
            update={"limits": (), "overall_limit": Decimal("999.0001")}
        )
        with pytest.raises(RuntimeError, match="rollback"):
            async with transaction_scope(resources.session_factory) as session:
                await service.put_budget(session, owner, replacement, budget_id)
                raise RuntimeError("rollback")
        async with transaction_scope(resources.session_factory) as session:
            preserved = await service.get_budget(session, owner, budget_id)
            assert len(preserved.limits) == 1
            assert preserved.overall_limit is None
            replaced = await service.put_budget(session, owner, replacement, budget_id)
            assert replaced.limits == []
            assert replaced.overall_limit == Decimal("999.0001")

        async with transaction_scope(resources.session_factory) as session:
            await service.archive_budget(session, owner, budget_id)
            await service.archive_budget(session, owner, budget_id)
            await service.archive_account(session, owner, account_id)
        async with transaction_scope(resources.session_factory) as session:
            assert (
                await service.repository.budgets(
                    session, owner, limit=10, offset=0, archived=False
                )
                == ()
            )
            assert (
                len(
                    await service.repository.budgets(
                        session, owner, limit=10, offset=0, archived=True
                    )
                )
                == 1
            )
            assert (
                await service.get_liability(session, owner, account_id)
            ).outstanding_amount == Decimal("765.4321")
            with pytest.raises(ApplicationError) as error:
                await service.put_budget(session, owner, replacement, budget_id)
            assert error.value.status_code == 409
            with pytest.raises(ApplicationError) as error:
                await service.update_account(
                    session, owner, account_id, AccountMetadataRequest(name="Renamed")
                )
            assert error.value.status_code == 409
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(delete(User).where(User.id.in_((owner, other))))
        await resources.dispose()
