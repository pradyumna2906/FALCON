"""Statement-import traceability model."""

from uuid import UUID

from falcon_api.infrastructure.persistence import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import (
    ImportSourceType,
    ImportStatus,
    enum_sql_values,
)
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class ImportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one user-owned attempt to ingest a financial file."""

    __tablename__ = "import_jobs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_import_jobs_user_id_id",
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
        Index(
            "ix_import_jobs_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_import_jobs_user_id_users",
        ),
        nullable=False,
    )
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
