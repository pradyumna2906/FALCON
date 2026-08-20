"""Statement-import traceability model."""

from __future__ import annotations

from uuid import UUID

from falcon_api.infrastructure.persistence import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import (
    ImportDateOrder,
    ImportSourceType,
    ImportStatus,
    enum_sql_values,
)
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ImportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one user-owned attempt to ingest a financial file."""

    __tablename__ = "import_jobs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_import_jobs_user_id_id",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_import_jobs_user_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_import_jobs_owner_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "file_fingerprint",
            name="uq_import_jobs_user_fingerprint",
        ),
        CheckConstraint(
            f"source_type IN ({enum_sql_values(ImportSourceType)})",
            name="source_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({enum_sql_values(ImportStatus)})",
            name="status_allowed",
        ),
        CheckConstraint(
            f"date_order IN ({enum_sql_values(ImportDateOrder)})",
            name="date_order_allowed",
        ),
        CheckConstraint(
            "header_row BETWEEN 1 AND 50",
            name="header_row_bounded",
        ),
        CheckConstraint(
            "sheet_name IS NULL OR length(trim(sheet_name)) > 0",
            name="sheet_name_not_blank",
        ),
        CheckConstraint(
            "file_fingerprint ~ '^[0-9a-f]{64}$'",
            name="file_fingerprint_sha256_hex",
        ),
        CheckConstraint(
            "accepted_count >= 0",
            name="accepted_count_non_negative",
        ),
        CheckConstraint(
            "rejected_count >= 0",
            name="rejected_count_non_negative",
        ),
        CheckConstraint(
            (
                "completed_at IS NULL OR started_at IS NULL OR "
                "completed_at >= started_at"
            ),
            name="completion_not_before_start",
        ),
        CheckConstraint(
            (
                "(status = 'pending' AND started_at IS NULL "
                "AND completed_at IS NULL) OR "
                "(status = 'processing' AND started_at IS NOT NULL "
                "AND completed_at IS NULL) OR "
                "(status IN ('completed', 'partial', 'failed') "
                "AND started_at IS NOT NULL AND completed_at IS NOT NULL)"
            ),
            name="lifecycle_consistent",
        ),
        CheckConstraint(
            (
                "(status IN ('pending', 'processing') "
                "AND accepted_count = 0 AND rejected_count = 0) OR "
                "(status = 'completed' AND accepted_count > 0 "
                "AND rejected_count = 0) OR "
                "(status = 'partial' AND accepted_count > 0 "
                "AND rejected_count > 0) OR "
                "(status = 'failed' AND accepted_count = 0)"
            ),
            name="reconciliation_consistent",
        ),
        Index(
            "ix_import_jobs_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    source_type: Mapped[ImportSourceType] = mapped_column(
        String(32),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    file_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    date_order: Mapped[ImportDateOrder] = mapped_column(
        String(16),
        nullable=False,
    )
    header_row: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(31), nullable=True)
    status: Mapped[ImportStatus] = mapped_column(
        String(16),
        default=ImportStatus.PENDING,
        nullable=False,
    )
    started_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )
    completed_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failure_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    issues_truncated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    issues: Mapped[list[ImportJobIssue]] = relationship(
        back_populates="import_job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ImportJobIssue.row_number, ImportJobIssue.id",
    )


class ImportJobIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist one bounded, sanitized reconciliation issue for an import."""

    __tablename__ = "import_job_issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.id"],
            name="fk_import_job_issues_owner_job",
            ondelete="CASCADE",
        ),
        CheckConstraint("row_number >= 1", name="row_number_positive"),
        CheckConstraint(
            "length(trim(code)) > 0",
            name="code_not_blank",
        ),
        CheckConstraint(
            "length(trim(message)) > 0",
            name="message_not_blank",
        ),
        Index(
            "ix_import_job_issues_job_row",
            "import_job_id",
            "row_number",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    import_job_id: Mapped[UUID] = mapped_column(nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(200), nullable=False)

    import_job: Mapped[ImportJob] = relationship(back_populates="issues")
