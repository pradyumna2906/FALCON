"""Application workflow for atomic authenticated statement imports."""

from dataclasses import dataclass
from pathlib import PurePath
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.imports.extraction import extract_statement
from falcon_api.imports.normalization import (
    file_fingerprint,
    normalize_statement,
    reject_existing_duplicates,
)
from falcon_api.imports.repository import ImportJobValues, ImportRepository
from falcon_api.models.enums import ImportStatus
from falcon_api.models.import_job import ImportJob
from falcon_api.schemas.imports import StatementImportOptions
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value


_IMPORT_FINGERPRINT_CONSTRAINT: Final = "uq_import_jobs_user_fingerprint"


@dataclass(frozen=True, slots=True)
class StatementImportCommand:
    """Trusted upload metadata and bounded private file content."""

    filename: str
    content_type: str
    content: bytes
    options: StatementImportOptions


class ImportService:
    """Own extraction, normalization, reconciliation, and atomic loading."""

    def __init__(
        self,
        *,
        repository: ImportRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or ImportRepository()
        self._clock = clock or SystemClock()

    async def process(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        timezone: str,
        command: StatementImportCommand,
    ) -> ImportJob:
        """Process one ephemeral statement and atomically load accepted rows."""
        account = await self._repository.get_active_account(
            session,
            user_id=user_id,
            account_id=command.options.account_id,
        )
        if account is None:
            raise ApplicationError(
                code="account_not_found",
                message="The requested account was not found.",
                status_code=404,
            )

        fingerprint = file_fingerprint(command.content)
        if await self._repository.find_by_fingerprint(
            session,
            user_id=user_id,
            fingerprint=fingerprint,
        ) is not None:
            raise _duplicate_import()

        safe_filename = _safe_filename(command.filename)
        statement = extract_statement(
            command.content,
            filename=safe_filename,
            content_type=command.content_type,
            options=command.options,
        )
        normalized = normalize_statement(
            statement,
            date_order=command.options.date_order,
            account_currency=account.currency,
            today=self._clock.now().astimezone(ZoneInfo(timezone)).date(),
        )
        candidates = frozenset(
            row.external_source_hash for row in normalized.rows
        )
        existing = await self._repository.find_existing_hashes(
            session,
            user_id=user_id,
            account_id=account.id,
            hashes=candidates,
        )
        normalized = reject_existing_duplicates(
            normalized,
            existing_hashes=existing,
        )

        now = self._clock.now()
        try:
            async with session.begin_nested():
                job = await self._repository.create_job(
                    session,
                    user_id=user_id,
                    values=ImportJobValues(
                        account_id=account.id,
                        source_type=command.options.source_type,
                        original_filename=safe_filename,
                        file_fingerprint=fingerprint,
                        date_order=command.options.date_order,
                        header_row=command.options.header_row,
                        sheet_name=command.options.sheet_name,
                    ),
                    now=now,
                )
        except IntegrityError as exc:
            if _constraint_name(exc) == _IMPORT_FINGERPRINT_CONSTRAINT:
                raise _duplicate_import() from None
            raise

        await self._repository.start_job(
            session,
            user_id=user_id,
            job=job,
            now=now,
        )
        try:
            async with session.begin_nested():
                await self._repository.create_transactions(
                    session,
                    user_id=user_id,
                    account_id=account.id,
                    job_id=job.id,
                    rows=normalized.rows,
                    now=now,
                )
                issues = await self._repository.create_issues(
                    session,
                    user_id=user_id,
                    job_id=job.id,
                    issues=normalized.issues,
                    now=now,
                )
        except Exception:
            await self._repository.finalize_job(
                session,
                user_id=user_id,
                job=job,
                status=ImportStatus.FAILED,
                accepted_count=0,
                rejected_count=(
                    normalized.accepted_count + normalized.rejected_count
                ),
                issues_truncated=normalized.issues_truncated,
                failure_summary="ledger_write_failed",
                now=self._clock.now(),
            )
            set_committed_value(job, "issues", [])
            return job

        status = _completion_status(
            accepted_count=normalized.accepted_count,
            rejected_count=normalized.rejected_count,
        )
        await self._repository.finalize_job(
            session,
            user_id=user_id,
            job=job,
            status=status,
            accepted_count=normalized.accepted_count,
            rejected_count=normalized.rejected_count,
            issues_truncated=normalized.issues_truncated,
            failure_summary=None,
            now=self._clock.now(),
        )
        set_committed_value(job, "issues", list(issues))
        return job

    async def get_job(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        job_id: UUID,
    ) -> ImportJob:
        """Return one owned import job or the bounded absent response."""
        job = await self._repository.get_job(
            session,
            user_id=user_id,
            job_id=job_id,
        )
        if job is None:
            raise ApplicationError(
                code="import_job_not_found",
                message="The requested import job was not found.",
                status_code=404,
            )
        return job


def _completion_status(
    *,
    accepted_count: int,
    rejected_count: int,
) -> ImportStatus:
    if accepted_count == 0:
        return ImportStatus.FAILED
    if rejected_count > 0:
        return ImportStatus.PARTIAL
    return ImportStatus.COMPLETED


def _safe_filename(filename: str) -> str:
    value = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    value = PurePath(value).name
    if (
        not value
        or value in {".", ".."}
        or len(value) > 255
        or any(ord(character) < 32 for character in value)
    ):
        raise ApplicationError(
            code="unsupported_import_file",
            message="The import file format is unsupported.",
            status_code=415,
        )
    return value


def _duplicate_import() -> ApplicationError:
    return ApplicationError(
        code="duplicate_import",
        message="This statement file was already imported.",
        status_code=409,
    )


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)
