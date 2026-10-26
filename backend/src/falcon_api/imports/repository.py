"""User-scoped persistence for statement imports and atomic ledger loading."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from falcon_api.imports.normalization import NormalizedImportRow
from falcon_api.models.account import Account
from falcon_api.models.enums import (
    ImportDateOrder,
    ImportSourceType,
    ImportStatus,
    TransactionSourceType,
    TransactionStatus,
)
from falcon_api.models.import_job import ImportJob, ImportJobIssue
from falcon_api.models.ledger import Transaction
from falcon_api.schemas.imports import ImportRowIssue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@dataclass(frozen=True, slots=True)
class ImportJobValues:
    """Complete server-controlled values for one pending import job."""

    account_id: UUID
    source_type: ImportSourceType
    original_filename: str
    file_fingerprint: str
    date_order: ImportDateOrder
    header_row: int
    sheet_name: str | None
    adapter_name: str | None = None
    balance_reconciled: bool | None = None


class ImportRepository:
    """Persist import state without crossing authenticated ownership."""

    async def get_active_account(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        account_id: UUID,
    ) -> Account | None:
        """Return one active account owned by the authenticated user."""
        return await session.scalar(
            select(Account).where(
                Account.user_id == user_id,
                Account.id == account_id,
                Account.archived_at.is_(None),
            )
        )

    async def find_by_fingerprint(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        fingerprint: str,
    ) -> ImportJob | None:
        """Resolve an exact-file retry only inside one user's namespace."""
        return await session.scalar(
            select(ImportJob).where(
                ImportJob.user_id == user_id,
                ImportJob.file_fingerprint == fingerprint,
            )
        )

    async def get_job(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        job_id: UUID,
    ) -> ImportJob | None:
        """Return one owned job with its bounded ordered issues."""
        statement = (
            select(ImportJob)
            .options(selectinload(ImportJob.issues))
            .where(
                ImportJob.user_id == user_id,
                ImportJob.id == job_id,
            )
        )
        return await session.scalar(statement)

    async def create_job(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        values: ImportJobValues,
        now: datetime,
    ) -> ImportJob:
        """Create and flush one pending import job."""
        job = ImportJob(
            id=uuid4(),
            user_id=user_id,
            account_id=values.account_id,
            source_type=values.source_type,
            original_filename=values.original_filename,
            file_fingerprint=values.file_fingerprint,
            date_order=values.date_order,
            header_row=values.header_row,
            sheet_name=values.sheet_name,
            adapter_name=values.adapter_name,
            balance_reconciled=values.balance_reconciled,
            status=ImportStatus.PENDING,
            started_at=None,
            completed_at=None,
            accepted_count=0,
            rejected_count=0,
            failure_summary=None,
            issues_truncated=False,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.flush()
        return job

    async def start_job(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        job: ImportJob,
        now: datetime,
    ) -> None:
        """Move an owned pending job into processing."""
        _require_job_owner(user_id=user_id, job=job)
        job.status = ImportStatus.PROCESSING
        job.started_at = now
        job.updated_at = now
        await session.flush()

    async def find_existing_hashes(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        account_id: UUID,
        hashes: frozenset[str],
    ) -> frozenset[str]:
        """Return only candidate hashes already present for one owned account."""
        if not hashes:
            return frozenset()
        statement = select(Transaction.external_source_hash).where(
            Transaction.user_id == user_id,
            Transaction.account_id == account_id,
            Transaction.external_source_hash.in_(hashes),
        )
        values = await session.scalars(statement)
        return frozenset(value for value in values.all() if value is not None)

    async def create_transactions(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        account_id: UUID,
        job_id: UUID,
        rows: tuple[NormalizedImportRow, ...],
        now: datetime,
    ) -> tuple[Transaction, ...]:
        """Add all normalized rows and perform one atomic flush."""
        transactions = tuple(
            Transaction(
                id=uuid4(),
                user_id=user_id,
                account_id=account_id,
                category_id=None,
                import_job_id=job_id,
                transfer_group_id=None,
                transaction_type=row.transaction_type,
                amount=row.signed_amount,
                transaction_date=row.transaction_date,
                description=row.description,
                merchant_name=row.merchant_name,
                source_type=TransactionSourceType.IMPORT,
                external_source_hash=row.external_source_hash,
                status=TransactionStatus.POSTED,
                is_user_modified=False,
                created_at=now,
                updated_at=now,
            )
            for row in rows
        )
        session.add_all(transactions)
        await session.flush()
        return transactions

    async def create_issues(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        job_id: UUID,
        issues: tuple[ImportRowIssue, ...],
        now: datetime,
    ) -> tuple[ImportJobIssue, ...]:
        """Persist only bounded sanitized reconciliation issues."""
        records = tuple(
            ImportJobIssue(
                id=uuid4(),
                user_id=user_id,
                import_job_id=job_id,
                row_number=issue.row_number,
                code=issue.code.value,
                message=issue.message,
                created_at=now,
                updated_at=now,
            )
            for issue in issues
        )
        session.add_all(records)
        await session.flush()
        return records

    async def finalize_job(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        job: ImportJob,
        status: ImportStatus,
        accepted_count: int,
        rejected_count: int,
        issues_truncated: bool,
        failure_summary: str | None,
        now: datetime,
    ) -> None:
        """Finalize one owned job after its ledger savepoint resolves."""
        _require_job_owner(user_id=user_id, job=job)
        job.status = status
        job.accepted_count = accepted_count
        job.rejected_count = rejected_count
        job.issues_truncated = issues_truncated
        job.failure_summary = failure_summary
        job.completed_at = now
        job.updated_at = now
        await session.flush()


def _require_job_owner(*, user_id: UUID, job: ImportJob) -> None:
    if job.user_id != user_id:
        raise ValueError("Import job does not belong to the specified user.")
