"""Add digital-PDF statement provenance and reconciliation metadata.

Revision ID: d8f3a2c7b419
Revises: c5a9e0b2d641
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d8f3a2c7b419"
down_revision: str | Sequence[str] | None = "c5a9e0b2d641"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the selected adapter and optional balance check."""
    op.add_column(
        "import_jobs",
        sa.Column("adapter_name", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "import_jobs",
        sa.Column("balance_reconciled", sa.Boolean(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_import_jobs_adapter_name_not_blank"),
        "import_jobs",
        "adapter_name IS NULL OR length(trim(adapter_name)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_import_jobs_adapter_matches_source"),
        "import_jobs",
        "(source_type = 'bank_statement' AND adapter_name IS NOT NULL) OR "
        "(source_type <> 'bank_statement' AND adapter_name IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_import_jobs_balance_reconciliation_matches_source"),
        "import_jobs",
        "balance_reconciled IS NULL OR source_type = 'bank_statement'",
    )


def downgrade() -> None:
    """Remove digital-PDF statement metadata."""
    op.drop_constraint(
        op.f("ck_import_jobs_balance_reconciliation_matches_source"),
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_import_jobs_adapter_matches_source"),
        "import_jobs",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_import_jobs_adapter_name_not_blank"),
        "import_jobs",
        type_="check",
    )
    op.drop_column("import_jobs", "balance_reconciled")
    op.drop_column("import_jobs", "adapter_name")
