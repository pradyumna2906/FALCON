"""Add Phase 6 statement-import persistence.

Revision ID: c5a9e0b2d641
Revises: 7fff19ce50be
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c5a9e0b2d641"
down_revision: str | Sequence[str] | None = "7fff19ce50be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist target accounts, import options, and sanitized row issues."""
    op.add_column(
        "import_jobs",
        sa.Column("account_id", sa.Uuid(), nullable=False),
    )
    op.add_column(
        "import_jobs",
        sa.Column("date_order", sa.String(length=16), nullable=False),
    )
    op.add_column(
        "import_jobs",
        sa.Column("header_row", sa.Integer(), nullable=False),
    )
    op.add_column(
        "import_jobs",
        sa.Column("sheet_name", sa.String(length=31), nullable=True),
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "issues_truncated",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.alter_column("import_jobs", "issues_truncated", server_default=None)
    op.create_foreign_key(
        "fk_import_jobs_owner_account",
        "import_jobs",
        "accounts",
        ["user_id", "account_id"],
        ["user_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_import_jobs_date_order_allowed",
        "import_jobs",
        "date_order IN ('day_first', 'month_first', 'year_first')",
    )
    op.create_check_constraint(
        "ck_import_jobs_header_row_bounded",
        "import_jobs",
        "header_row BETWEEN 1 AND 50",
    )
    op.create_check_constraint(
        "ck_import_jobs_sheet_name_not_blank",
        "import_jobs",
        "sheet_name IS NULL OR length(trim(sheet_name)) > 0",
    )
    op.create_check_constraint(
        "ck_import_jobs_file_fingerprint_sha256_hex",
        "import_jobs",
        "file_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_import_jobs_lifecycle_consistent",
        "import_jobs",
        "(status = 'pending' AND started_at IS NULL "
        "AND completed_at IS NULL) OR "
        "(status = 'processing' AND started_at IS NOT NULL "
        "AND completed_at IS NULL) OR "
        "(status IN ('completed', 'partial', 'failed') "
        "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_import_jobs_reconciliation_consistent",
        "import_jobs",
        "(status IN ('pending', 'processing') "
        "AND accepted_count = 0 AND rejected_count = 0) OR "
        "(status = 'completed' AND accepted_count > 0 "
        "AND rejected_count = 0) OR "
        "(status = 'partial' AND accepted_count > 0 "
        "AND rejected_count > 0) OR "
        "(status = 'failed' AND accepted_count = 0)",
    )
    op.create_table(
        "import_job_issues",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(code)) > 0",
            name=op.f("ck_import_job_issues_code_not_blank"),
        ),
        sa.CheckConstraint(
            "length(trim(message)) > 0",
            name=op.f("ck_import_job_issues_message_not_blank"),
        ),
        sa.CheckConstraint(
            "row_number >= 1",
            name=op.f("ck_import_job_issues_row_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.id"],
            name="fk_import_job_issues_owner_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_job_issues")),
    )
    op.create_index(
        "ix_import_job_issues_job_row",
        "import_job_issues",
        ["import_job_id", "row_number"],
        unique=False,
    )


def downgrade() -> None:
    """Remove Phase 6 statement-import persistence."""
    op.drop_index(
        "ix_import_job_issues_job_row",
        table_name="import_job_issues",
    )
    op.drop_table("import_job_issues")
    op.drop_constraint(
        "ck_import_jobs_reconciliation_consistent",
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_import_jobs_lifecycle_consistent",
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_import_jobs_file_fingerprint_sha256_hex",
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_import_jobs_sheet_name_not_blank",
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_import_jobs_header_row_bounded",
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_import_jobs_date_order_allowed",
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        "fk_import_jobs_owner_account",
        "import_jobs",
        type_="foreignkey",
    )
    op.drop_column("import_jobs", "issues_truncated")
    op.drop_column("import_jobs", "sheet_name")
    op.drop_column("import_jobs", "header_row")
    op.drop_column("import_jobs", "date_order")
    op.drop_column("import_jobs", "account_id")
