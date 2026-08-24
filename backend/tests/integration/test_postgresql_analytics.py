"""Real PostgreSQL analytics aggregation and owner-isolation tests."""

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
from fastapi.testclient import TestClient
from sqlalchemy import delete

from falcon_api.analytics import (
    AnalyticsGranularity,
    AnalyticsPeriod,
    AnalyticsRepository,
)
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.main import create_app
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import (
    AccountType,
    CategoryKind,
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
    UserStatus,
)
from falcon_api.models.ledger import Transaction, TransferGroup
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
_NOW = datetime(2026, 8, 24, 8, tzinfo=UTC)
_PERIOD = AnalyticsPeriod(
    date_from=date(2026, 8, 1),
    date_to=date(2026, 8, 24),
    timezone="Asia/Kolkata",
)
_PASSWORD = "Analytics-Integration-Password-2026!"


def integration_settings() -> Settings:
    """Load ignored local PostgreSQL settings."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    """Ensure analytics tests use the current reviewed schema."""
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def test_live_aggregates_are_exact_currency_scoped_and_owner_isolated() -> None:
    """Exercise every 8.2 query against real PostgreSQL records."""
    asyncio.run(_exercise_live_aggregates())


def test_authenticated_analytics_api_returns_dashboard_ready_results() -> None:
    """Exercise both public analytics operations against real PostgreSQL."""
    settings = integration_settings()
    user_ids: list[UUID] = []

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            owner_id, token, account_id = _register_login_account(
                client,
                email=f"analytics-api-owner-{uuid4().hex}@falcon.test",
            )
            other_id, other_token, other_account_id = _register_login_account(
                client,
                email=f"analytics-api-other-{uuid4().hex}@falcon.test",
            )
            user_ids.extend((owner_id, other_id))
            _post_transaction(
                client,
                token=token,
                account_id=account_id,
                transaction_type=TransactionType.INCOME,
                amount="10000.0000",
                merchant="Employer",
            )
            _post_transaction(
                client,
                token=token,
                account_id=account_id,
                transaction_type=TransactionType.EXPENSE,
                amount="2500.0000",
                merchant="Swiggy",
            )
            _post_transaction(
                client,
                token=other_token,
                account_id=other_account_id,
                transaction_type=TransactionType.EXPENSE,
                amount="999999.0000",
                merchant="Must Not Leak",
            )
            headers = {"Authorization": f"Bearer {token}"}
            params = {
                "date_from": "2026-08-01",
                "date_to": "2026-08-24",
                "comparison": "none",
            }

            cash_flow = client.get(
                "/api/v1/analytics/cash-flow",
                headers=headers,
                params={**params, "granularity": "day"},
            )
            assert cash_flow.status_code == 200, cash_flow.text
            cash_body = cash_flow.json()
            assert cash_body["metrics"]["gross_income"]["value"] == (
                "10000.0000"
            )
            assert cash_body["metrics"]["total_expense"]["value"] == (
                "2500.0000"
            )
            assert cash_body["metrics"]["net_cash_flow"]["value"] == (
                "7500.0000"
            )
            assert cash_body["previous_period"] is None
            assert len(cash_body["series"]) == 1

            spending = client.get(
                "/api/v1/analytics/spending",
                headers=headers,
                params={**params, "limit": "10"},
            )
            assert spending.status_code == 200, spending.text
            spending_body = spending.json()
            assert spending_body["total_expense"]["value"] == "2500.0000"
            assert spending_body["categories"] == []
            assert spending_body["merchants"] == [
                {
                    "normalized_merchant": "swiggy",
                    "display_name": "Swiggy",
                    "amount": {"value": "2500.0000"},
                    "share": {"value": "1.000000"},
                    "transaction_count": 1,
                }
            ]
            assert spending_body["accounts"][0]["account_id"] == str(
                account_id
            )
            assert spending_body["accounts"][0]["amount"]["value"] == (
                "2500.0000"
            )
    finally:
        if user_ids:
            asyncio.run(_delete_users(integration_settings(), *user_ids))


async def _exercise_live_aggregates() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    owner_id = uuid4()
    other_id = uuid4()
    owner = _user(owner_id, "analytics-owner")
    other = _user(other_id, "analytics-other")
    inr_account = _account(owner_id, "Historical INR", "INR")
    usd_account = _account(owner_id, "USD Account", "USD")
    other_account = _account(other_id, "Other INR", "INR")
    income_category = _category(owner_id, "Salary", CategoryKind.INCOME)
    expense_category = _category(owner_id, "Dining", CategoryKind.EXPENSE)
    transfer_group = TransferGroup(
        id=uuid4(),
        user_id=owner_id,
        created_at=_NOW,
        updated_at=_NOW,
    )

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, other])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([inr_account, usd_account, other_account])
            session.add_all([income_category, expense_category, transfer_group])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all(
                [
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="10000",
                        transaction_type=TransactionType.INCOME,
                        transaction_date=date(2026, 8, 1),
                        category_id=income_category.id,
                        merchant="Employer",
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-2500",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 2),
                        category_id=expense_category.id,
                        merchant="SWIGGY",
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-50",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 2),
                        category_id=None,
                        merchant="swiggy",
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-100",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 2),
                        category_id=None,
                        merchant="Pending",
                        status=TransactionStatus.PENDING,
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-500",
                        transaction_type=TransactionType.TRANSFER,
                        transaction_date=date(2026, 8, 3),
                        category_id=None,
                        merchant=None,
                        transfer_group_id=transfer_group.id,
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="500",
                        transaction_type=TransactionType.TRANSFER,
                        transaction_date=date(2026, 8, 3),
                        category_id=None,
                        merchant=None,
                        transfer_group_id=transfer_group.id,
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-10",
                        transaction_type=TransactionType.ADJUSTMENT,
                        transaction_date=date(2026, 8, 4),
                        category_id=None,
                        merchant=None,
                    ),
                    _transaction(
                        owner_id,
                        usd_account.id,
                        amount="-99",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 5),
                        category_id=None,
                        merchant="USD Merchant",
                    ),
                    _transaction(
                        other_id,
                        other_account.id,
                        amount="999999",
                        transaction_type=TransactionType.INCOME,
                        transaction_date=date(2026, 8, 1),
                        category_id=None,
                        merchant="Must Not Leak",
                    ),
                ]
            )
        async with transaction_scope(resources.session_factory) as session:
            persisted = await session.get(Account, inr_account.id)
            assert persisted is not None
            persisted.archived_at = _NOW

        repository = AnalyticsRepository()
        async with transaction_scope(resources.session_factory) as session:
            summary = await repository.get_summary(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )
            daily = await repository.list_cash_flow_buckets(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
                granularity=AnalyticsGranularity.DAY,
            )
            categories = await repository.list_category_aggregates(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )
            merchants = await repository.list_merchant_aggregates(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )
            accounts = await repository.list_account_aggregates(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )

        assert summary.gross_income == Decimal("10000.0000")
        assert summary.total_expense == Decimal("2550.0000")
        assert summary.net_cash_flow == Decimal("7450.0000")
        assert summary.internal_transfer_volume == Decimal("500.0000")
        assert summary.net_adjustment == Decimal("-10.0000")
        assert summary.eligible_transaction_count == 3
        assert summary.categorized_transaction_count == 2
        assert summary.pending_count == 1
        assert summary.transfer_entry_count == 2
        assert summary.adjustment_count == 1
        assert summary.other_currency_count == 1
        assert summary.latest_transaction_date == date(2026, 8, 2)
        assert len(daily) == 2
        assert sum(row.gross_income for row in daily) == Decimal("10000.0000")
        assert sum(row.total_expense for row in daily) == Decimal("2550.0000")
        assert {row.name: row.amount for row in categories} == {
            "Salary": Decimal("10000.0000"),
            "Dining": Decimal("2500.0000"),
        }
        assert {row.normalized_merchant for row in merchants} == {
            "employer",
            "swiggy",
        }
        swiggy = next(
            row for row in merchants if row.normalized_merchant == "swiggy"
        )
        assert swiggy.total_expense == Decimal("2550.0000")
        assert swiggy.expense_transaction_count == 2
        assert swiggy.income_transaction_count == 0
        assert accounts[0].account_id == inr_account.id
        assert accounts[0].gross_income == Decimal("10000.0000")
        assert accounts[0].total_expense == Decimal("2550.0000")
        assert accounts[0].income_transaction_count == 1
        assert accounts[0].expense_transaction_count == 2
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(
                delete(User).where(User.id.in_((owner_id, other_id)))
            )
        await resources.dispose()


def _register_login_account(
    client: TestClient,
    *,
    email: str,
) -> tuple[UUID, str, UUID]:
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
    user_id = UUID(registration.json()["id"])
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    account = client.post(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"Analytics {uuid4().hex[:8]}",
            "account_type": "bank",
            "opening_balance": "0.0000",
            "opening_balance_date": "2026-08-01",
        },
    )
    assert account.status_code == 201, account.text
    return user_id, token, UUID(account.json()["id"])


def _post_transaction(
    client: TestClient,
    *,
    token: str,
    account_id: UUID,
    transaction_type: TransactionType,
    amount: str,
    merchant: str,
) -> None:
    response = client.post(
        "/api/v1/transactions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": str(account_id),
            "category_id": None,
            "transaction_type": transaction_type.value,
            "amount": amount,
            "transaction_date": "2026-08-24",
            "description": f"Analytics API {transaction_type.value}",
            "merchant_name": merchant,
        },
    )
    assert response.status_code == 201, response.text


async def _delete_users(settings: Settings, *user_ids: UUID) -> None:
    resources = create_database_resources(settings)
    try:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(delete(User).where(User.id.in_(user_ids)))
    finally:
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


def _account(user_id: UUID, name: str, currency: str) -> Account:
    return Account(
        id=uuid4(),
        user_id=user_id,
        name=name,
        account_type=AccountType.BANK,
        institution_name=None,
        masked_reference=None,
        currency=currency,
        opening_balance=Decimal("0"),
        opening_balance_date=date(2026, 1, 1),
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _category(user_id: UUID, name: str, kind: CategoryKind) -> Category:
    return Category(
        id=uuid4(),
        user_id=user_id,
        name=name,
        normalized_name=f"analytics_{name.lower()}",
        classification_code=None,
        kind=kind,
        parent_id=None,
        is_system=False,
        display_order=0,
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _transaction(
    user_id: UUID,
    account_id: UUID,
    *,
    amount: str,
    transaction_type: TransactionType,
    transaction_date: date,
    category_id: UUID | None,
    merchant: str | None,
    status: TransactionStatus = TransactionStatus.POSTED,
    transfer_group_id: UUID | None = None,
) -> Transaction:
    source_type = TransactionSourceType.MANUAL
    if transaction_type is TransactionType.TRANSFER:
        source_type = TransactionSourceType.TRANSFER
    elif transaction_type is TransactionType.ADJUSTMENT:
        source_type = TransactionSourceType.ADJUSTMENT
    return Transaction(
        id=uuid4(),
        user_id=user_id,
        account_id=account_id,
        category_id=category_id,
        import_job_id=None,
        transfer_group_id=transfer_group_id,
        transaction_type=transaction_type,
        amount=Decimal(amount),
        transaction_date=transaction_date,
        description=f"Analytics {transaction_type.value}",
        merchant_name=merchant,
        source_type=source_type,
        external_source_hash=None,
        status=status,
        is_user_modified=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
