"""Application-service tests for atomic statement import workflows."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from falcon_api.auth.clock import Clock
from falcon_api.core.errors import ApplicationError
from falcon_api.imports.repository import ImportRepository
from falcon_api.imports.service import ImportService, StatementImportCommand
from falcon_api.models.account import Account
from falcon_api.models.enums import (
    AccountType,
    ImportDateOrder,
    ImportSourceType,
    ImportStatus,
)
from falcon_api.models.import_job import ImportJob
from falcon_api.schemas.imports import StatementImportOptions
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


_NOW = datetime(2026, 8, 20, 15, 30, tzinfo=UTC)


class _NestedContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.begin_nested = Mock(return_value=_NestedContext())
    return session


def _account(user_id: UUID) -> Account:
    return Account(
        id=uuid4(),
        user_id=user_id,
        name="Primary Bank",
        account_type=AccountType.BANK,
        institution_name=None,
        masked_reference=None,
        currency="INR",
        opening_balance=Decimal("0"),
        opening_balance_date=date(2026, 8, 1),
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _job(user_id: UUID, account_id: UUID) -> ImportJob:
    return ImportJob(
        id=uuid4(),
        user_id=user_id,
        account_id=account_id,
        source_type="csv",
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


def _command(account_id: UUID, *, content: bytes | None = None) -> StatementImportCommand:
    return StatementImportCommand(
        filename="statement.csv",
        content_type="text/csv",
        content=content
        or (
            b"Date,Description,Amount\n"
            b"20/08/2026,Salary,50000\n"
            b"19/08/2026,Invalid,0\n"
        ),
        options=StatementImportOptions(
            account_id=account_id,
            source_type="csv",
        ),
    )


def _service(repository: AsyncMock) -> ImportService:
    clock = Mock(spec=Clock)
    clock.now.return_value = _NOW
    return ImportService(repository=repository, clock=clock)


def _repository(user_id: UUID) -> tuple[AsyncMock, Account, ImportJob]:
    repository = AsyncMock(spec=ImportRepository)
    account = _account(user_id)
    job = _job(user_id, account.id)
    repository.get_active_account.return_value = account
    repository.find_by_fingerprint.return_value = None
    repository.find_existing_hashes.return_value = frozenset()
    repository.create_job.return_value = job
    repository.create_issues.return_value = ()
    return repository, account, job


def _integrity_error(constraint: str) -> IntegrityError:
    original = Exception("safe test error")
    original.diag = SimpleNamespace(constraint_name=constraint)
    return IntegrityError("statement", {}, original)


def test_process_authorizes_normalizes_and_finalizes_partial_job() -> None:
    user_id = uuid4()
    repository, account, job = _repository(user_id)

    result = asyncio.run(
        _service(repository).process(
            _session(),
            user_id=user_id,
            timezone="Asia/Kolkata",
            command=_command(account.id),
        )
    )

    assert result is job
    values = repository.create_job.await_args.kwargs["values"]
    assert values.account_id == account.id
    assert values.original_filename == "statement.csv"
    assert len(values.file_fingerprint) == 64
    rows = repository.create_transactions.await_args.kwargs["rows"]
    assert len(rows) == 1
    assert rows[0].signed_amount == Decimal("50000")
    finalized = repository.finalize_job.await_args.kwargs
    assert finalized["status"] is ImportStatus.PARTIAL
    assert finalized["accepted_count"] == 1
    assert finalized["rejected_count"] == 1


def test_process_rejects_missing_or_cross_user_account() -> None:
    repository = AsyncMock(spec=ImportRepository)
    repository.get_active_account.return_value = None

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).process(
                _session(),
                user_id=uuid4(),
                timezone="Asia/Kolkata",
                command=_command(uuid4()),
            )
        )

    assert info.value.code == "account_not_found"
    repository.find_by_fingerprint.assert_not_awaited()


def test_process_rejects_preexisting_file_fingerprint() -> None:
    user_id = uuid4()
    repository, account, _ = _repository(user_id)
    repository.find_by_fingerprint.return_value = Mock()

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).process(
                _session(),
                user_id=user_id,
                timezone="Asia/Kolkata",
                command=_command(account.id),
            )
        )

    assert info.value.code == "duplicate_import"
    assert info.value.status_code == 409
    repository.create_job.assert_not_awaited()


def test_process_rejects_password_for_non_pdf_source() -> None:
    user_id = uuid4()
    repository, account, _ = _repository(user_id)
    command = _command(account.id)
    command = StatementImportCommand(
        filename=command.filename,
        content_type=command.content_type,
        content=command.content,
        options=command.options,
        file_password="must-not-be-retained",
    )

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).process(
                _session(),
                user_id=user_id,
                timezone="Asia/Kolkata",
                command=command,
            )
        )

    assert info.value.code == "validation_error"
    repository.find_by_fingerprint.assert_not_awaited()


def test_pdf_balance_mismatch_stops_before_job_creation(monkeypatch) -> None:
    user_id = uuid4()
    repository, account, _ = _repository(user_id)
    options = StatementImportOptions(
        account_id=account.id,
        source_type=ImportSourceType.BANK_STATEMENT,
    )
    command = StatementImportCommand(
        filename="statement.pdf",
        content_type="application/pdf",
        content=b"%PDF-test",
        options=options,
    )
    extracted = SimpleNamespace(adapter_name="generic_digital_pdf_v1")
    normalized = SimpleNamespace(balance_reconciled=False)
    monkeypatch.setattr(
        "falcon_api.imports.service.extract_statement",
        Mock(return_value=extracted),
    )
    monkeypatch.setattr(
        "falcon_api.imports.service.normalize_statement",
        Mock(return_value=normalized),
    )

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).process(
                _session(),
                user_id=user_id,
                timezone="Asia/Kolkata",
                command=command,
            )
        )

    assert info.value.code == "statement_balance_mismatch"
    repository.create_job.assert_not_awaited()


def test_process_filters_account_scoped_existing_transaction_hashes() -> None:
    user_id = uuid4()
    repository, account, _ = _repository(user_id)
    first = _command(
        account.id,
        content=(
            b"Date,Description,Amount,Reference\n"
            b"20/08/2026,Salary,50000,SAL-1\n"
        ),
    )

    asyncio.run(
        _service(repository).process(
            _session(),
            user_id=user_id,
            timezone="Asia/Kolkata",
            command=first,
        )
    )
    candidates = repository.find_existing_hashes.await_args.kwargs["hashes"]
    repository.reset_mock()
    repository.get_active_account.return_value = account
    repository.find_by_fingerprint.return_value = None
    repository.find_existing_hashes.return_value = candidates
    repository.create_job.return_value = _job(user_id, account.id)
    repository.create_issues.return_value = ()

    asyncio.run(
        _service(repository).process(
            _session(),
            user_id=user_id,
            timezone="Asia/Kolkata",
            command=first,
        )
    )

    assert repository.create_transactions.await_args.kwargs["rows"] == ()
    finalized = repository.finalize_job.await_args.kwargs
    assert finalized["status"] is ImportStatus.FAILED
    assert finalized["rejected_count"] == 1


def test_ledger_failure_rolls_back_savepoint_and_finalizes_failed_job() -> None:
    user_id = uuid4()
    repository, account, job = _repository(user_id)
    repository.create_transactions.side_effect = RuntimeError("forced rollback")

    result = asyncio.run(
        _service(repository).process(
            _session(),
            user_id=user_id,
            timezone="Asia/Kolkata",
            command=_command(account.id),
        )
    )

    assert result is job
    repository.create_issues.assert_not_awaited()
    finalized = repository.finalize_job.await_args.kwargs
    assert finalized["status"] is ImportStatus.FAILED
    assert finalized["accepted_count"] == 0
    assert finalized["rejected_count"] == 2
    assert finalized["failure_summary"] == "ledger_write_failed"


def test_fingerprint_race_maps_only_known_unique_constraint() -> None:
    user_id = uuid4()
    repository, account, _ = _repository(user_id)
    repository.create_job.side_effect = _integrity_error(
        "uq_import_jobs_user_fingerprint"
    )

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).process(
                _session(),
                user_id=user_id,
                timezone="Asia/Kolkata",
                command=_command(account.id),
            )
        )
    assert info.value.code == "duplicate_import"

    repository.create_job.side_effect = _integrity_error("other_constraint")
    with pytest.raises(IntegrityError):
        asyncio.run(
            _service(repository).process(
                _session(),
                user_id=user_id,
                timezone="Asia/Kolkata",
                command=_command(account.id),
            )
        )


def test_get_job_is_owner_scoped_and_absence_is_bounded() -> None:
    user_id = uuid4()
    repository = AsyncMock(spec=ImportRepository)
    expected = Mock()
    repository.get_job.return_value = expected
    service = _service(repository)

    result = asyncio.run(
        service.get_job(_session(), user_id=user_id, job_id=uuid4())
    )
    assert result is expected
    assert repository.get_job.await_args.kwargs["user_id"] == user_id

    repository.get_job.return_value = None
    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            service.get_job(_session(), user_id=user_id, job_id=uuid4())
        )
    assert info.value.code == "import_job_not_found"


@pytest.mark.parametrize("filename", ["", "..", "bad\x00name.csv"])
def test_process_rejects_unsafe_filename(filename: str) -> None:
    user_id = uuid4()
    repository, account, _ = _repository(user_id)
    command = _command(account.id)
    command = StatementImportCommand(
        filename=filename,
        content_type=command.content_type,
        content=command.content,
        options=command.options,
    )

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).process(
                _session(),
                user_id=user_id,
                timezone="Asia/Kolkata",
                command=command,
            )
        )
    assert info.value.code == "unsupported_import_file"
