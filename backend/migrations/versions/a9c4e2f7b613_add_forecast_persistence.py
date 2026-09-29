"""Add immutable owner-scoped forecast persistence.

Revision ID: a9c4e2f7b613
Revises: f7b2d4e8a901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a9c4e2f7b613"
down_revision: str | Sequence[str] | None = "f7b2d4e8a901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install append-only forecast provenance and point estimates."""
    op.create_table(
        "forecast_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("history_start", sa.Date(), nullable=False),
        sa.Column("history_end", sa.Date(), nullable=False),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_last_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("forecast_start", sa.Date(), nullable=False),
        sa.Column("forecast_end", sa.Date(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("quality_policy_version", sa.String(length=32), nullable=False),
        sa.Column(
            "evaluation_policy_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("feature_policy_version", sa.String(length=32), nullable=True),
        sa.Column("selection_policy_version", sa.String(length=32), nullable=False),
        sa.Column(
            "uncertainty_policy_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("model_code", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("model_parameters", postgresql.JSONB(), nullable=False),
        sa.Column("candidate_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("selection_metric", sa.String(length=8), nullable=False),
        sa.Column("validation_mae", sa.Numeric(20, 6), nullable=False),
        sa.Column("validation_rmse", sa.Numeric(20, 6), nullable=False),
        sa.Column("validation_wape", sa.Numeric(20, 6), nullable=True),
        sa.Column("validation_bias", sa.Numeric(20, 6), nullable=False),
        sa.Column("test_mae", sa.Numeric(20, 6), nullable=False),
        sa.Column("test_rmse", sa.Numeric(20, 6), nullable=False),
        sa.Column("test_wape", sa.Numeric(20, 6), nullable=True),
        sa.Column("test_bias", sa.Numeric(20, 6), nullable=False),
        sa.Column("uncertainty_method", sa.String(length=64), nullable=False),
        sa.Column("uncertainty_reliability", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_forecast_runs_currency_iso"),
        ),
        sa.CheckConstraint(
            "forecast_end >= forecast_start",
            name=op.f("ck_forecast_runs_forecast_valid"),
        ),
        sa.CheckConstraint(
            "granularity IN ('day', 'month')",
            name=op.f("ck_forecast_runs_granularity_allowed"),
        ),
        sa.CheckConstraint(
            "history_end >= history_start",
            name=op.f("ck_forecast_runs_history_valid"),
        ),
        sa.CheckConstraint(
            "horizon > 0",
            name=op.f("ck_forecast_runs_horizon_positive"),
        ),
        sa.CheckConstraint(
            "length(trim(model_code)) > 0 AND length(trim(model_version)) > 0",
            name=op.f("ck_forecast_runs_model_identity_not_blank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(model_parameters) = 'object' AND "
            "jsonb_typeof(candidate_evidence) = 'object'",
            name=op.f("ck_forecast_runs_evidence_objects"),
        ),
        sa.CheckConstraint(
            "selection_metric IN ('wape', 'mae')",
            name=op.f("ck_forecast_runs_selection_metric_allowed"),
        ),
        sa.CheckConstraint(
            "target IN ('gross_income', 'total_expense', 'net_cash_flow', "
            "'savings_amount')",
            name=op.f("ck_forecast_runs_target_allowed"),
        ),
        sa.CheckConstraint(
            "test_mae >= 0 AND test_rmse >= 0 AND "
            "(test_wape IS NULL OR test_wape >= 0)",
            name=op.f("ck_forecast_runs_test_metrics_non_negative"),
        ),
        sa.CheckConstraint(
            "uncertainty_reliability IN ('provisional', 'normal')",
            name=op.f("ck_forecast_runs_uncertainty_reliability_allowed"),
        ),
        sa.CheckConstraint(
            "validation_mae >= 0 AND validation_rmse >= 0 AND "
            "(validation_wape IS NULL OR validation_wape >= 0)",
            name=op.f("ck_forecast_runs_validation_metrics_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_forecast_runs_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_runs")),
        sa.UniqueConstraint(
            "user_id",
            "id",
            name="uq_forecast_runs_user_id_id",
        ),
    )
    op.create_index(
        "ix_forecast_runs_user_currency_created",
        "forecast_runs",
        ["user_id", "currency", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_forecast_runs_user_target_created",
        "forecast_runs",
        ["user_id", "target", "created_at"],
        unique=False,
    )
    op.create_table(
        "forecast_points",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("forecast_run_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("expected_value", sa.Numeric(19, 4), nullable=False),
        sa.Column("lower_80", sa.Numeric(19, 4), nullable=False),
        sa.Column("upper_80", sa.Numeric(19, 4), nullable=False),
        sa.Column("lower_95", sa.Numeric(19, 4), nullable=False),
        sa.Column("upper_95", sa.Numeric(19, 4), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lower_95 <= lower_80 AND lower_80 <= expected_value AND "
            "expected_value <= upper_80 AND upper_80 <= upper_95",
            name=op.f("ck_forecast_points_bands_nested"),
        ),
        sa.CheckConstraint(
            "step > 0",
            name=op.f("ck_forecast_points_step_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "forecast_run_id"],
            ["forecast_runs.user_id", "forecast_runs.id"],
            name="fk_forecast_points_owner_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_points")),
        sa.UniqueConstraint(
            "forecast_run_id",
            "period_start",
            name="uq_forecast_points_run_period",
        ),
        sa.UniqueConstraint(
            "forecast_run_id",
            "step",
            name="uq_forecast_points_run_step",
        ),
    )
    op.create_index(
        "ix_forecast_points_user_run_step",
        "forecast_points",
        ["user_id", "forecast_run_id", "step"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION reject_forecast_record_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'forecast records are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_forecast_runs_immutable
        BEFORE UPDATE ON forecast_runs
        FOR EACH ROW EXECUTE FUNCTION reject_forecast_record_update()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_forecast_points_immutable
        BEFORE UPDATE ON forecast_points
        FOR EACH ROW EXECUTE FUNCTION reject_forecast_record_update()
        """
    )


def downgrade() -> None:
    """Remove immutable forecast persistence."""
    op.execute("DROP TRIGGER trg_forecast_points_immutable ON forecast_points")
    op.execute("DROP TRIGGER trg_forecast_runs_immutable ON forecast_runs")
    op.execute("DROP FUNCTION reject_forecast_record_update()")
    op.drop_index(
        "ix_forecast_points_user_run_step",
        table_name="forecast_points",
    )
    op.drop_table("forecast_points")
    op.drop_index(
        "ix_forecast_runs_user_target_created",
        table_name="forecast_runs",
    )
    op.drop_index(
        "ix_forecast_runs_user_currency_created",
        table_name="forecast_runs",
    )
    op.drop_table("forecast_runs")
