"""Unit contracts for user-scoped import persistence."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from falcon_api.imports.normalization import NormalizedImportRow
from falcon_api.imports.repository import ImportJobValues, ImportRepository
from falcon_api.models.enums import (
    ImportDateOrder,
    ImportSourceType,
    ImportStatus,
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.import_job import ImportJob
from falcon_api.schemas.imports import ImportIssueCode, ImportRowIssue
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession


_NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    session.add_all = Mock()
    return session


def _job(user_id: UUID) -> ImportJob:
    return ImportJob(
        id=uuid4(),
        user_id=user_id,
        account_id=uuid4(),
        source_type=ImportSourceType.CSV,
        original_filename="statement.csv",
        file_fingerprint="a" * 64,
        date_order=ImportDateOrder.DAY_FIRST,
        header_row=1,
        sheet_name=None,
        status=ImportStatus.PENDING,
        started_at=None,
        completed_at=None,
        accepted_count=0,
        rejected_count=0,
        failure_summary=None,
        issues_truncated=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _values(account_id: UUID) -> ImportJobValues:
    return ImportJobValues(
        account_id=account_id,
        source_type=ImportSourceType.CSV,
        original_filename="statement.csv",
        file_fingerprint="a" * 64,
        date_order=ImportDateOrder.DAY_FIRST,
        header_row=1,
        sheet_name=None,
    )


def _normalized_row() -> NormalizedImportRow:
    return NormalizedImportRow(
        row_number=2,
        transaction_type=TransactionType.EXPENSE,
        signed_amount=Decimal("-1250.5000"),
        transaction_date=date(2026, 8, 20),
        description="Groceries",
        merchant_name="Local Market",
        source_reference="REF-1",
        external_source_hash="b" * 64,
    )


def _compiled_scalar(session: AsyncMock) -> tuple[str, dict[str, object]]:
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_get_active_account_is_owned_and_excludes_archived() -> None:
    session = _session()
    user_id = uuid4()
    account_id = uuid4()

    asyncio.run(
        ImportRepository().get_active_account(
            session,
            user_id=user_id,
            account_id=account_id,
        )
    )

    query, params = _compiled_scalar(session)
    assert "accounts.user_id =" in query
    assert "accounts.id =" in query
    assert "accounts.archived_at IS NULL" in query
    assert user_id in params.values()
    assert account_id in params.values()


def test_fingerprint_and_job_reads_are_owner_scoped() -> None:
    repository = ImportRepository()
    user_id = uuid4()
    session = _session()

    asyncio.run(
        repository.find_by_fingerprint(
            session,
            user_id=user_id,
            fingerprint="a" * 64,
        )
    )
    fingerprint_query, params = _compiled_scalar(session)
    assert "import_jobs.user_id =" in fingerprint_query
    assert "import_jobs.file_fingerprint =" in fingerprint_query
    assert user_id in params.values()

    session.reset_mock()
    asyncio.run(
        repository.get_job(session, user_id=user_id, job_id=uuid4())
    )
    job_query, _ = _compiled_scalar(session)
    assert "import_jobs.user_id =" in job_query
    assert "import_jobs.id =" in job_query


def test_create_and_start_job_sets_complete_server_values() -> None:
    repository = ImportRepository()
    session = _session()
    user_id = uuid4()
    account_id = uuid4()

    job = asyncio.run(
        repository.create_job(
            session,
            user_id=user_id,
            values=_values(account_id),
            now=_NOW,
        )
    )

    assert job.user_id == user_id
    assert job.account_id == account_id
    assert job.status is ImportStatus.PENDING
    assert job.started_at is None
    session.add.assert_called_once_with(job)

    asyncio.run(
        repository.start_job(
            session,
            user_id=user_id,
            job=job,
            now=_NOW,
        )
    )
    assert job.status is ImportStatus.PROCESSING
    assert job.started_at == _NOW


def test_existing_hash_query_is_bounded_by_user_account_and_candidates() -> None:
    session = _session()
    scalar_result = Mock()
    scalar_result.all.return_value = ["a" * 64, None]
    session.scalars.return_value = scalar_result
    user_id = uuid4()
    account_id = uuid4()

    result = asyncio.run(
        ImportRepository().find_existing_hashes(
            session,
            user_id=user_id,
            account_id=account_id,
            hashes=frozenset({"a" * 64, "b" * 64}),
        )
    )

    statement = session.scalars.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    query = str(compiled)
    assert result == frozenset({"a" * 64})
    assert "transactions.user_id =" in query
    assert "transactions.account_id =" in query
    assert "transactions.external_source_hash IN" in query


def test_empty_candidate_hashes_skip_database_query() -> None:
    session = _session()

    result = asyncio.run(
        ImportRepository().find_existing_hashes(
            session,
            user_id=uuid4(),
            account_id=uuid4(),
            hashes=frozenset(),
        )
    )

    assert result == frozenset()
    session.scalars.assert_not_awaited()


def test_create_transactions_uses_import_provenance_and_one_flush() -> None:
    session = _session()
    user_id = uuid4()
    account_id = uuid4()
    job_id = uuid4()

    transactions = asyncio.run(
        ImportRepository().create_transactions(
            session,
            user_id=user_id,
            account_id=account_id,
            job_id=job_id,
            rows=(_normalized_row(),),
            now=_NOW,
        )
    )

    transaction = transactions[0]
    assert transaction.user_id == user_id
    assert transaction.account_id == account_id
    assert transaction.import_job_id == job_id
    assert transaction.source_type is TransactionSourceType.IMPORT
    assert transaction.status is TransactionStatus.POSTED
    assert transaction.amount == Decimal("-1250.5000")
    assert transaction.category_id is None
    assert transaction.is_user_modified is False
    session.add_all.assert_called_once_with(transactions)
    session.flush.assert_awaited_once_with()


def test_create_issues_persists_only_sanitized_public_values() -> None:
    session = _session()
    user_id = uuid4()
    job_id = uuid4()
    issue = ImportRowIssue(
        row_number=4,
        code=ImportIssueCode.INVALID_DATE,
        message="The transaction date is invalid.",
    )

    records = asyncio.run(
        ImportRepository().create_issues(
            session,
            user_id=user_id,
            job_id=job_id,
            issues=(issue,),
            now=_NOW,
        )
    )

    assert records[0].user_id == user_id
    assert records[0].import_job_id == job_id
    assert records[0].code == "invalid_date"
    assert records[0].message == issue.message
    session.add_all.assert_called_once_with(records)


def test_finalize_job_enforces_owner_and_updates_reconciliation() -> None:
    repository = ImportRepository()
    session = _session()
    user_id = uuid4()
    job = _job(user_id)

    asyncio.run(
        repository.finalize_job(
            session,
            user_id=user_id,
            job=job,
            status=ImportStatus.PARTIAL,
            accepted_count=2,
            rejected_count=1,
            issues_truncated=True,
            failure_summary=None,
            now=_NOW,
        )
    )

    assert job.status is ImportStatus.PARTIAL
    assert job.accepted_count == 2
    assert job.rejected_count == 1
    assert job.issues_truncated is True
    assert job.completed_at == _NOW

    with pytest.raises(ValueError, match="does not belong"):
        asyncio.run(
            repository.start_job(
                session,
                user_id=uuid4(),
                job=job,
                now=_NOW,
            )
        )
