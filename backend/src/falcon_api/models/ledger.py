"""Financial transaction ledger and internal-transfer models."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from falcon_api.infrastructure.persistence import (
    Base,
    MoneyAmount,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import (
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
    enum_sql_values,
)
from falcon_api.models.import_job import ImportJob
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class TransferGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Connect the two ledger entries of one internal transfer."""

    __tablename__ = "transfer_groups"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_transfer_groups_user_id_id",
        ),
        Index(
            "ix_transfer_groups_user_created",
            "user_id",
            "created_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_transfer_groups_user_id_users",
        ),
        nullable=False,
    )

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="transfer_group",
        cascade="all, delete-orphan",
        overlaps="account,import_job",
        passive_deletes=True,
    )


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one signed financial movement against one account."""

    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transactions_user_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_transactions_owner_account",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.id"],
            name="fk_transactions_owner_import_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "transfer_group_id"],
            ["transfer_groups.user_id", "transfer_groups.id"],
            name="fk_transactions_owner_transfer_group",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_transactions_user_id_id",
        ),
        CheckConstraint(
            f"transaction_type IN ({enum_sql_values(TransactionType)})",
            name="transaction_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({enum_sql_values(TransactionStatus)})",
            name="status_allowed",
        ),
        CheckConstraint(
            (
                "source_type IN "
                f"({enum_sql_values(TransactionSourceType)})"
            ),
            name="source_type_allowed",
        ),
        CheckConstraint(
            "amount <> 0",
            name="amount_non_zero",
        ),
        CheckConstraint(
            (
                "(transaction_type = 'transfer' "
                "AND transfer_group_id IS NOT NULL) OR "
                "(transaction_type <> 'transfer' "
                "AND transfer_group_id IS NULL)"
            ),
            name="transfer_group_consistent",
        ),
        CheckConstraint(
            (
                "(source_type = 'import' AND import_job_id IS NOT NULL) OR "
                "(source_type <> 'import' AND import_job_id IS NULL)"
            ),
            name="import_job_consistent",
        ),
        CheckConstraint(
            "length(trim(description)) > 0",
            name="description_not_blank",
        ),
        Index(
            "ix_transactions_user_date",
            "user_id",
            "transaction_date",
        ),
        Index(
            "ix_transactions_account_date",
            "account_id",
            "transaction_date",
        ),
        Index(
            "ix_transactions_category_date",
            "category_id",
            "transaction_date",
        ),
        Index(
            "ix_transactions_import_job",
            "import_job_id",
            postgresql_where=text("import_job_id IS NOT NULL"),
        ),
        Index(
            "ix_transactions_transfer_group",
            "transfer_group_id",
            postgresql_where=text("transfer_group_id IS NOT NULL"),
        ),
        Index(
            "uq_transactions_user_account_source_hash",
            "user_id",
            "account_id",
            "external_source_hash",
            unique=True,
            postgresql_where=text("external_source_hash IS NOT NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "categories.id",
            ondelete="RESTRICT",
            name="fk_transactions_category_id_categories",
        ),
        nullable=True,
    )
    import_job_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
    )
    transfer_group_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        String(16),
        nullable=False,
    )
    amount: Mapped[MoneyAmount] = mapped_column(
        nullable=False,
    )
    transaction_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    merchant_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    source_type: Mapped[TransactionSourceType] = mapped_column(
        String(16),
        nullable=False,
    )
    external_source_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    status: Mapped[TransactionStatus] = mapped_column(
        String(16),
        default=TransactionStatus.POSTED,
        nullable=False,
    )
    is_user_modified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    account: Mapped[Account] = relationship(
        overlaps="import_job,transactions,transfer_group",
    )
    category: Mapped[Category | None] = relationship()
    import_job: Mapped[ImportJob | None] = relationship(
        overlaps="account,transactions,transfer_group",
    )
    transfer_group: Mapped[TransferGroup | None] = relationship(
        back_populates="transactions",
        overlaps="account,import_job",
    )
