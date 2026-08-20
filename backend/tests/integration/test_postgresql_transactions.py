"""Real PostgreSQL transaction lifecycle, isolation, and concurrency tests."""

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
from falcon_api.auth.clock import SystemClock
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.main import create_app
from falcon_api.models.account import Account
from falcon_api.models.enums import AccountType, TransactionType, UserStatus
from falcon_api.models.ledger import Transaction, TransferGroup
from falcon_api.models.user import User
from falcon_api.transactions import (
    ManualTransactionCommand,
    TransactionCursorCodec,
    TransactionService,
    TransferCommand,
)
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_PASSWORD = "Transaction-Integration-Password-2026!"
_SIGNING_SECRET = "phase-5-transaction-integration-secret-2026"


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
    """Ensure transaction tests run against the reviewed migration head."""
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def _transaction_payload(
    account_id: str,
    *,
    amount: str,
    description: str,
) -> dict[str, object]:
    return {
        "account_id": account_id,
        "category_id": None,
        "transaction_type": "expense",
        "amount": amount,
        "transaction_date": date.today().isoformat(),
        "description": description,
        "merchant_name": None,
    }


def test_authenticated_transaction_api_lifecycle_and_isolation() -> None:
    """Exercise setup, CRUD, pagination, transfer, and cross-user denial."""
    settings = integration_settings()
    emails = (
        f"transaction-api-a-{uuid4().hex}@example.com",
        f"transaction-api-b-{uuid4().hex}@example.com",
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
        assert login.status_code == 200, login.text
        return login.json()["access_token"]

    def create_account(
        client: TestClient,
        token: str,
        name: str,
    ) -> dict[str, object]:
        response = client.post(
            "/api/v1/accounts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": name,
                "account_type": "bank",
                "opening_balance": "10000.0000",
                "opening_balance_date": date.today().isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            first_token = register_and_login(client, emails[0])
            second_token = register_and_login(client, emails[1])
            first_headers = {"Authorization": f"Bearer {first_token}"}
            second_headers = {"Authorization": f"Bearer {second_token}"}

            source = create_account(client, first_token, "Primary Bank")
            destination = create_account(client, first_token, "Savings Bank")
            create_account(client, second_token, "Other User Bank")

            duplicate = client.post(
                "/api/v1/accounts",
                headers=first_headers,
                json={
                    "name": "Primary Bank",
                    "account_type": "bank",
                    "opening_balance_date": date.today().isoformat(),
                },
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["error"]["code"] == (
                "account_name_conflict"
            )

            accounts = client.get("/api/v1/accounts", headers=first_headers)
            assert accounts.status_code == 200
            assert {item["id"] for item in accounts.json()["items"]} == {
                source["id"],
                destination["id"],
            }
            categories = client.get(
                "/api/v1/categories",
                headers=first_headers,
            )
            assert categories.status_code == 200

            created_ids: list[str] = []
            for number in range(3):
                created = client.post(
                    "/api/v1/transactions",
                    headers=first_headers,
                    json=_transaction_payload(
                        source["id"],
                        amount=f"{number + 1}.0000",
                        description=f"Lifecycle expense {number}",
                    ),
                )
                assert created.status_code == 201, created.text
                assert created.json()["amount"] == f"{number + 1}.0000"
                created_ids.append(created.json()["id"])

            isolated = client.get(
                f"/api/v1/transactions/{created_ids[0]}",
                headers=second_headers,
            )
            assert isolated.status_code == 404
            assert isolated.json()["error"]["code"] == (
                "transaction_not_found"
            )

            first_page = client.get(
                "/api/v1/transactions",
                headers=first_headers,
                params={"limit": 2},
            )
            assert first_page.status_code == 200
            first_body = first_page.json()
            assert len(first_body["items"]) == 2
            assert first_body["next_cursor"] is not None

            second_page = client.get(
                "/api/v1/transactions",
                headers=first_headers,
                params={"limit": 2, "cursor": first_body["next_cursor"]},
            )
            assert second_page.status_code == 200
            page_ids = {
                item["id"]
                for item in first_body["items"] + second_page.json()["items"]
            }
            assert page_ids == set(created_ids)

            stolen_cursor = client.get(
                "/api/v1/transactions",
                headers=second_headers,
                params={"limit": 2, "cursor": first_body["next_cursor"]},
            )
            assert stolen_cursor.status_code == 422
            assert stolen_cursor.json()["error"]["code"] == (
                "invalid_transaction_cursor"
            )

            replaced = client.put(
                f"/api/v1/transactions/{created_ids[0]}",
                headers=first_headers,
                json=_transaction_payload(
                    destination["id"],
                    amount="25.5000",
                    description="Replaced lifecycle expense",
                ),
            )
            assert replaced.status_code == 200
            assert replaced.json()["account_id"] == destination["id"]
            assert replaced.json()["is_user_modified"] is True

            deleted = client.delete(
                f"/api/v1/transactions/{created_ids[1]}",
                headers=first_headers,
            )
            assert deleted.status_code == 204
            missing = client.get(
                f"/api/v1/transactions/{created_ids[1]}",
                headers=first_headers,
            )
            assert missing.status_code == 404

            transfer = client.post(
                "/api/v1/transfers",
                headers=first_headers,
                json={
                    "source_account_id": source["id"],
                    "destination_account_id": destination["id"],
                    "amount": "500.0000",
                    "transaction_date": date.today().isoformat(),
                    "description": "Move to savings",
                },
            )
            assert transfer.status_code == 201, transfer.text
            transfer_body = transfer.json()
            assert transfer_body["debit"]["amount"] == "500.0000"
            assert transfer_body["credit"]["amount"] == "500.0000"
            assert transfer_body["debit"]["account_id"] == source["id"]
            assert transfer_body["credit"]["account_id"] == (
                destination["id"]
            )

            immutable = client.delete(
                f"/api/v1/transactions/{transfer_body['debit']['id']}",
                headers=first_headers,
            )
            assert immutable.status_code == 409
            assert immutable.json()["error"]["code"] == (
                "transaction_conflict"
            )
    finally:
        if user_ids:
            asyncio.run(
                _delete_users(settings, *user_ids),
                loop_factory=asyncio.SelectorEventLoop,
            )


def test_opposite_transfers_use_deadlock_safe_lock_order() -> None:
    """Run opposite transfers concurrently and retain two valid pairs."""
    asyncio.run(
        _exercise_opposite_transfers(),
        loop_factory=asyncio.SelectorEventLoop,
    )


def test_failed_transaction_unit_of_work_rolls_back() -> None:
    """Verify an application failure leaves no partial manual entry."""
    asyncio.run(
        _exercise_transaction_rollback(),
        loop_factory=asyncio.SelectorEventLoop,
    )


async def _exercise_transaction_rollback() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    now = SystemClock().now()
    owner = User(
        id=uuid4(),
        email=f"transaction-rollback-{uuid4().hex}@falcon.test",
        status=UserStatus.ACTIVE,
        display_name="Transaction Rollback User",
        timezone="UTC",
        default_currency="INR",
        email_verified_at=None,
        created_at=now,
        updated_at=now,
    )
    account = _account(owner.id, "Rollback Account", now)
    service = TransactionService(
        cursor_codec=TransactionCursorCodec(signing_secret=_SIGNING_SECRET),
    )

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, account])

        with pytest.raises(RuntimeError, match="force transaction rollback"):
            async with transaction_scope(
                resources.session_factory
            ) as session:
                await service.create_manual(
                    session,
                    user_id=owner.id,
                    timezone="UTC",
                    command=ManualTransactionCommand(
                        account_id=account.id,
                        category_id=None,
                        transaction_type=TransactionType.EXPENSE,
                        amount=Decimal("99.0000"),
                        transaction_date=now.date(),
                        description="Must be rolled back",
                        merchant_name=None,
                    ),
                )
                raise RuntimeError("force transaction rollback")

        async with transaction_scope(resources.session_factory) as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.user_id == owner.id)
            )
        assert count == 0
    finally:
        await _delete_users_with_resources(resources, owner.id)
        await resources.dispose()


async def _exercise_opposite_transfers() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    now = SystemClock().now()
    owner = User(
        id=uuid4(),
        email=f"transfer-race-{uuid4().hex}@falcon.test",
        status=UserStatus.ACTIVE,
        display_name="Transfer Race User",
        timezone="UTC",
        default_currency="INR",
        email_verified_at=None,
        created_at=now,
        updated_at=now,
    )
    first = _account(owner.id, "Concurrent One", now)
    second = _account(owner.id, "Concurrent Two", now)
    service = TransactionService(
        cursor_codec=TransactionCursorCodec(signing_secret=_SIGNING_SECRET),
    )

    async def transfer(source_id: UUID, destination_id: UUID) -> UUID:
        async with transaction_scope(resources.session_factory) as session:
            result = await service.create_transfer(
                session,
                user_id=owner.id,
                timezone="UTC",
                command=TransferCommand(
                    source_account_id=source_id,
                    destination_account_id=destination_id,
                    amount=Decimal("10.0000"),
                    transaction_date=now.date(),
                    description="Concurrent opposite transfer",
                ),
            )
            return result.id

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, first, second])

        group_ids = await asyncio.wait_for(
            asyncio.gather(
                transfer(first.id, second.id),
                transfer(second.id, first.id),
            ),
            timeout=10,
        )
        assert len(set(group_ids)) == 2

        async with transaction_scope(resources.session_factory) as session:
            entries = (
                await session.scalars(
                    select(Transaction).where(
                        Transaction.transfer_group_id.in_(group_ids)
                    )
                )
            ).all()
            group_count = await session.scalar(
                select(func.count())
                .select_from(TransferGroup)
                .where(TransferGroup.id.in_(group_ids))
            )

        assert group_count == 2
        assert len(entries) == 4
        for group_id in group_ids:
            pair = [
                entry
                for entry in entries
                if entry.transfer_group_id == group_id
            ]
            assert len(pair) == 2
            assert sum(entry.amount for entry in pair) == Decimal("0")
            assert len({entry.account_id for entry in pair}) == 2
    finally:
        await _delete_users_with_resources(resources, owner.id)
        await resources.dispose()


def _account(user_id: UUID, name: str, now: datetime) -> Account:
    return Account(
        id=uuid4(),
        user_id=user_id,
        name=name,
        account_type=AccountType.BANK,
        institution_name=None,
        masked_reference=None,
        currency="INR",
        opening_balance=Decimal("0"),
        opening_balance_date=now.date(),
        archived_at=None,
        created_at=now,
        updated_at=now,
    )


async def _delete_users(settings: Settings, *user_ids: UUID) -> None:
    resources = create_database_resources(settings)
    try:
        await _delete_users_with_resources(resources, *user_ids)
    finally:
        await resources.dispose()


async def _delete_users_with_resources(resources, *user_ids: UUID) -> None:
    async with transaction_scope(resources.session_factory) as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))
