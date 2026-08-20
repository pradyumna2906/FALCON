"""Real PostgreSQL statement-import ownership and rollback tests."""

import asyncio
import os
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.imports import ImportRepository, ImportService
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.main import create_app
from falcon_api.models.enums import ImportStatus, TransactionSourceType
from falcon_api.models.import_job import ImportJob
from falcon_api.models.ledger import Transaction
from falcon_api.models.user import User
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
_PASSWORD = "Statement-Import-Integration-Password-2026!"


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
    """Ensure import tests run against the latest reviewed migration."""
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def test_authenticated_import_lifecycle_retry_and_isolation() -> None:
    """Prove ledger loading, reconciliation, retry, and owner isolation."""
    settings = integration_settings()
    user_ids: list[UUID] = []

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            first_token, first_id = _register_and_login(client, "owner")
            second_token, second_id = _register_and_login(client, "other")
            user_ids.extend((first_id, second_id))
            account_id = _create_account(client, first_token)
            first_headers = {"Authorization": f"Bearer {first_token}"}
            second_headers = {"Authorization": f"Bearer {second_token}"}
            statement = _partial_statement()

            cross_account = _upload(
                client,
                token=second_token,
                account_id=account_id,
                statement=statement,
            )
            assert cross_account.status_code == 404
            assert cross_account.json()["error"]["code"] == "account_not_found"

            imported = _upload(
                client,
                token=first_token,
                account_id=account_id,
                statement=statement,
            )
            assert imported.status_code == 201, imported.text
            body = imported.json()
            assert body["status"] == "partial"
            assert body["accepted_count"] == 1
            assert body["rejected_count"] == 1
            assert body["issues"][0]["code"] == "zero_amount"
            assert "file_fingerprint" not in body
            assert "failure_summary" not in body

            owned = client.get(
                f"/api/v1/imports/{body['id']}",
                headers=first_headers,
            )
            assert owned.status_code == 200
            assert owned.json() == body

            isolated = client.get(
                f"/api/v1/imports/{body['id']}",
                headers=second_headers,
            )
            assert isolated.status_code == 404
            assert isolated.json()["error"]["code"] == "import_job_not_found"

            retry = _upload(
                client,
                token=first_token,
                account_id=account_id,
                statement=statement,
            )
            assert retry.status_code == 409
            assert retry.json()["error"]["code"] == "duplicate_import"

        imported_count, import_job_id = asyncio.run(
            _imported_transaction_summary(settings, first_id),
            loop_factory=asyncio.SelectorEventLoop,
        )
        assert imported_count == 1
        assert str(import_job_id) == body["id"]
    finally:
        if user_ids:
            asyncio.run(
                _delete_users(settings, *user_ids),
                loop_factory=asyncio.SelectorEventLoop,
            )


def test_database_write_failure_rolls_back_rows_but_commits_failed_job() -> None:
    """Prove a flushed ledger batch is removed while its failed job remains."""
    settings = integration_settings()
    user_ids: list[UUID] = []

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            token, user_id = _register_and_login(client, "rollback")
            user_ids.append(user_id)
            account_id = _create_account(client, token)
            client.app.state.import_service = ImportService(
                repository=_FailAfterFlushRepository()
            )

            response = _upload(
                client,
                token=token,
                account_id=account_id,
                statement=_valid_statement(),
            )

            assert response.status_code == 201, response.text
            body = response.json()
            assert body["status"] == "failed"
            assert body["accepted_count"] == 0
            assert body["rejected_count"] == 1
            status_response = client.get(
                f"/api/v1/imports/{body['id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert status_response.status_code == 200
            assert status_response.json()["status"] == "failed"

        transaction_count, job = asyncio.run(
            _rollback_summary(settings, user_id, UUID(body["id"])),
            loop_factory=asyncio.SelectorEventLoop,
        )
        assert transaction_count == 0
        assert job is not None
        assert job.status == ImportStatus.FAILED
        assert job.failure_summary == "ledger_write_failed"
    finally:
        if user_ids:
            asyncio.run(
                _delete_users(settings, *user_ids),
                loop_factory=asyncio.SelectorEventLoop,
            )


class _FailAfterFlushRepository(ImportRepository):
    """Inject a failure after PostgreSQL has flushed the accepted batch."""

    async def create_transactions(self, *args, **kwargs):
        await super().create_transactions(*args, **kwargs)
        raise RuntimeError("forced post-flush ledger failure")


def _register_and_login(
    client: TestClient,
    label: str,
) -> tuple[str, UUID]:
    email = f"statement-import-{label}-{uuid4().hex}@example.com"
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
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"], UUID(registration.json()["id"])


def _create_account(client: TestClient, token: str) -> UUID:
    response = client.post(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Statement Import Account",
            "account_type": "bank",
            "opening_balance": "10000.0000",
            "opening_balance_date": _today().isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _upload(
    client: TestClient,
    *,
    token: str,
    account_id: UUID,
    statement: bytes,
):
    return client.post(
        "/api/v1/imports",
        headers={"Authorization": f"Bearer {token}"},
        data={"account_id": str(account_id), "source_type": "csv"},
        files={"file": ("statement.csv", statement, "text/csv")},
    )


def _valid_statement() -> bytes:
    current = _today().strftime("%d/%m/%Y")
    return (
        "Date,Description,Amount,Reference\n"
        f"{current},Salary,50000,SALARY-1\n"
    ).encode()


def _partial_statement() -> bytes:
    current = _today().strftime("%d/%m/%Y")
    return (
        "Date,Description,Amount,Reference\n"
        f"{current},Salary,50000,SALARY-1\n"
        f"{current},Invalid zero,0,ZERO-1\n"
    ).encode()


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


async def _imported_transaction_summary(
    settings: Settings,
    user_id: UUID,
) -> tuple[int, UUID | None]:
    resources = create_database_resources(settings)
    try:
        async with transaction_scope(resources.session_factory) as session:
            statement = select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.source_type == TransactionSourceType.IMPORT,
            )
            rows = (await session.scalars(statement)).all()
            return len(rows), rows[0].import_job_id if rows else None
    finally:
        await resources.dispose()


async def _rollback_summary(
    settings: Settings,
    user_id: UUID,
    job_id: UUID,
) -> tuple[int, ImportJob | None]:
    resources = create_database_resources(settings)
    try:
        async with transaction_scope(resources.session_factory) as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.user_id == user_id)
            )
            job = await session.scalar(
                select(ImportJob).where(
                    ImportJob.user_id == user_id,
                    ImportJob.id == job_id,
                )
            )
            return int(count or 0), job
    finally:
        await resources.dispose()


async def _delete_users(settings: Settings, *user_ids: UUID) -> None:
    resources = create_database_resources(settings)
    try:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(delete(User).where(User.id.in_(user_ids)))
    finally:
        await resources.dispose()
