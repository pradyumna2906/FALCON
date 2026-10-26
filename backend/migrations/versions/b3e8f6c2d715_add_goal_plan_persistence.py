"""Add immutable owner-scoped goal-plan persistence.

Revision ID: b3e8f6c2d715
Revises: a9c4e2f7b613
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b3e8f6c2d715"
down_revision: str | Sequence[str] | None = "a9c4e2f7b613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install immutable generated plans and append-only decision history."""
    op.create_table(
        "goal_plan_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_plan_id", sa.Uuid(), nullable=True),
        sa.Column("forecast_run_id", sa.Uuid(), nullable=True),
        sa.Column("deterministic_plan_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("planning_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("horizon_start", sa.Date(), nullable=True),
        sa.Column("horizon_end", sa.Date(), nullable=True),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("plan_policy_version", sa.String(length=32), nullable=False),
        sa.Column("capacity_policy_version", sa.String(length=32), nullable=True),
        sa.Column(
            "feasibility_policy_version", sa.String(length=32), nullable=False
        ),
        sa.Column("ranking_policy_version", sa.String(length=32), nullable=False),
        sa.Column("greedy_policy_version", sa.String(length=32), nullable=False),
        sa.Column(
            "optimization_policy_version", sa.String(length=32), nullable=False
        ),
        sa.Column("guardrail_policy_version", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("optimizer_status", sa.String(length=32), nullable=True),
        sa.Column("overall_feasibility", sa.String(length=24), nullable=False),
        sa.Column("solver_name", sa.String(length=64), nullable=True),
        sa.Column("solver_version", sa.String(length=64), nullable=True),
        sa.Column("allocation_band", sa.String(length=64), nullable=False),
        sa.Column("forecast_reliability", sa.String(length=24), nullable=False),
        sa.Column("emergency_reserve_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("available_savings", sa.Numeric(19, 4), nullable=False),
        sa.Column("allocated_savings", sa.Numeric(19, 4), nullable=False),
        sa.Column("unallocated_savings", sa.Numeric(19, 4), nullable=False),
        sa.Column("weighted_funding_score", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "greedy_weighted_funding_score", sa.Numeric(20, 6), nullable=False
        ),
        sa.Column(
            "guarded_fallback_weighted_funding_score",
            sa.Numeric(20, 6),
            nullable=False,
        ),
        sa.Column(
            "optimized_weighted_funding_score", sa.Numeric(20, 6), nullable=True
        ),
        sa.Column(
            "selected_score_delta_from_greedy", sa.Numeric(20, 6), nullable=False
        ),
        sa.Column("goal_count", sa.Integer(), nullable=False),
        sa.Column("feasible_goal_count", sa.Integer(), nullable=False),
        sa.Column("at_risk_goal_count", sa.Integer(), nullable=False),
        sa.Column("uncertain_goal_count", sa.Integer(), nullable=False),
        sa.Column("fully_funded_goal_count", sa.Integer(), nullable=False),
        sa.Column("deadline_met_goal_count", sa.Integer(), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_warnings", postgresql.JSONB(), nullable=False),
        sa.Column("guardrail_reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "feasible_goal_count + at_risk_goal_count + uncertain_goal_count "
            "= goal_count",
            name=op.f("ck_goal_plan_runs_assessment_counts_reconcile"),
        ),
        sa.CheckConstraint(
            "goal_count >= 0 AND feasible_goal_count >= 0 AND "
            "at_risk_goal_count >= 0 AND uncertain_goal_count >= 0 AND "
            "fully_funded_goal_count >= 0 AND deadline_met_goal_count >= 0",
            name=op.f("ck_goal_plan_runs_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_goal_plan_runs_currency_iso"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(assumptions) = 'array' AND "
            "jsonb_typeof(reason_codes) = 'array' AND "
            "jsonb_typeof(snapshot_warnings) = 'array' AND "
            "jsonb_typeof(guardrail_reason_codes) = 'array'",
            name=op.f("ck_goal_plan_runs_evidence_arrays"),
        ),
        sa.CheckConstraint(
            "snapshot_id ~ '^[0-9a-f]{64}$' AND "
            "deterministic_plan_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_goal_plan_runs_hashes_sha256_hex"),
        ),
        sa.CheckConstraint(
            "(horizon_start IS NULL AND horizon_end IS NULL) OR "
            "(horizon_start IS NOT NULL AND horizon_end >= horizon_start)",
            name=op.f("ck_goal_plan_runs_horizon_valid"),
        ),
        sa.CheckConstraint(
            "emergency_reserve_amount >= 0 AND available_savings >= 0 AND "
            "allocated_savings >= 0 AND unallocated_savings >= 0 AND "
            "allocated_savings + unallocated_savings = available_savings",
            name=op.f("ck_goal_plan_runs_money_totals_valid"),
        ),
        sa.CheckConstraint(
            "optimizer_status IS NULL OR optimizer_status IN "
            "('optimal', 'no_solution', 'solver_unavailable', "
            "'solver_failed', 'invalid_solution')",
            name=op.f("ck_goal_plan_runs_optimizer_status_allowed"),
        ),
        sa.CheckConstraint(
            "fully_funded_goal_count <= goal_count AND "
            "deadline_met_goal_count <= goal_count",
            name=op.f("ck_goal_plan_runs_outcome_counts_bounded"),
        ),
        sa.CheckConstraint(
            "overall_feasibility IN "
            "('fully_funded', 'feasible', 'at_risk', 'uncertain', "
            "'blocked', 'unavailable')",
            name=op.f("ck_goal_plan_runs_overall_feasibility_allowed"),
        ),
        sa.CheckConstraint(
            "weighted_funding_score >= 0 AND "
            "greedy_weighted_funding_score >= 0 AND "
            "guarded_fallback_weighted_funding_score >= 0 AND "
            "(optimized_weighted_funding_score IS NULL OR "
            "optimized_weighted_funding_score >= 0)",
            name=op.f("ck_goal_plan_runs_scores_non_negative"),
        ),
        sa.CheckConstraint(
            "strategy IN ('optimized', 'guarded_greedy_fallback', 'blocked')",
            name=op.f("ck_goal_plan_runs_strategy_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "forecast_run_id"],
            ["forecast_runs.user_id", "forecast_runs.id"],
            name="fk_goal_plan_runs_owner_forecast",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "predecessor_plan_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_runs_owner_predecessor",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_goal_plan_runs_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_plan_runs")),
        sa.UniqueConstraint("user_id", "id", name="uq_goal_plan_runs_user_id_id"),
    )
    op.create_index(
        "ix_goal_plan_runs_user_created",
        "goal_plan_runs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_goal_plan_runs_user_currency_created",
        "goal_plan_runs",
        ["user_id", "currency", "created_at"],
        unique=False,
    )

    op.create_table(
        "goal_plan_outcomes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_run_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("goal_name", sa.String(length=120), nullable=False),
        sa.Column("goal_type", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("target_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("current_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("starting_remaining_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("projected_remaining_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("protected_shortfall", sa.Numeric(19, 4), nullable=False),
        sa.Column("expected_shortfall", sa.Numeric(19, 4), nullable=False),
        sa.Column("expected_completion_period", sa.Date(), nullable=True),
        sa.Column("projected_completion_period", sa.Date(), nullable=True),
        sa.Column("deadline_met", sa.Boolean(), nullable=False),
        sa.Column("feasibility_state", sa.String(length=24), nullable=False),
        sa.Column("deadline_risk", sa.String(length=24), nullable=False),
        sa.Column("completion_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("evidence_reliability", sa.String(length=24), nullable=False),
        sa.Column("feasibility_reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("ranking_reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_amount > 0 AND current_amount >= 0 AND "
            "starting_remaining_amount >= 0 AND allocated_amount >= 0 AND "
            "projected_remaining_amount >= 0 AND protected_shortfall >= 0 AND "
            "expected_shortfall >= 0 AND "
            "allocated_amount <= starting_remaining_amount",
            name=op.f("ck_goal_plan_outcomes_amounts_valid"),
        ),
        sa.CheckConstraint(
            "length(trim(goal_name)) > 0",
            name=op.f("ck_goal_plan_outcomes_goal_name_not_blank"),
        ),
        sa.CheckConstraint(
            "goal_type IN ('travel', 'marriage', 'education', "
            "'emergency_fund', 'major_purchase', 'other')",
            name=op.f("ck_goal_plan_outcomes_goal_type_allowed"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_goal_plan_outcomes_priority_allowed"),
        ),
        sa.CheckConstraint(
            "feasibility_state IN ('funded', 'secure', 'feasible', "
            "'stretch', 'unlikely', 'indeterminate', 'overdue', "
            "'unavailable')",
            name=op.f("ck_goal_plan_outcomes_feasibility_state_allowed"),
        ),
        sa.CheckConstraint(
            "deadline_risk IN ('funded', 'low', 'moderate', 'high', "
            "'critical', 'overdue', 'unknown')",
            name=op.f("ck_goal_plan_outcomes_deadline_risk_allowed"),
        ),
        sa.CheckConstraint(
            "evidence_reliability IN ('normal', 'provisional', "
            "'limited_horizon', 'unavailable')",
            name=op.f("ck_goal_plan_outcomes_evidence_reliability_allowed"),
        ),
        sa.CheckConstraint(
            "completion_probability IS NULL OR "
            "(completion_probability >= 0 AND completion_probability <= 1)",
            name=op.f("ck_goal_plan_outcomes_probability_valid"),
        ),
        sa.CheckConstraint(
            "rank > 0",
            name=op.f("ck_goal_plan_outcomes_rank_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(feasibility_reason_codes) = 'array' AND "
            "jsonb_typeof(ranking_reason_codes) = 'array'",
            name=op.f("ck_goal_plan_outcomes_reason_arrays"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "plan_run_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_outcomes_owner_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_plan_outcomes")),
        sa.UniqueConstraint(
            "user_id",
            "plan_run_id",
            "id",
            name="uq_goal_plan_outcomes_owner_run_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "plan_run_id",
            "id",
            "goal_id",
            name="uq_goal_plan_outcomes_owner_run_id_goal",
        ),
        sa.UniqueConstraint(
            "plan_run_id", "goal_id", name="uq_goal_plan_outcomes_run_goal"
        ),
    )
    op.create_index(
        "ix_goal_plan_outcomes_user_run_rank",
        "goal_plan_outcomes",
        ["user_id", "plan_run_id", "rank"],
        unique=False,
    )

    op.create_table(
        "goal_plan_periods",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_run_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("available_capacity", sa.Numeric(19, 4), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("unallocated_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "available_capacity >= 0 AND allocated_amount >= 0 AND "
            "unallocated_amount >= 0 AND "
            "allocated_amount + unallocated_amount = available_capacity",
            name=op.f("ck_goal_plan_periods_totals_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "plan_run_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_periods_owner_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_plan_periods")),
        sa.UniqueConstraint(
            "user_id",
            "plan_run_id",
            "id",
            name="uq_goal_plan_periods_owner_run_id",
        ),
        sa.UniqueConstraint(
            "plan_run_id", "period_start", name="uq_goal_plan_periods_run_period"
        ),
    )
    op.create_index(
        "ix_goal_plan_periods_user_run_period",
        "goal_plan_periods",
        ["user_id", "plan_run_id", "period_start"],
        unique=False,
    )

    op.create_table(
        "goal_plan_allocations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_run_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("cumulative_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("projected_remaining_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rank > 0 AND amount > 0 AND cumulative_amount > 0 AND "
            "projected_remaining_amount >= 0",
            name=op.f("ck_goal_plan_allocations_values_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "plan_run_id", "outcome_id", "goal_id"],
            [
                "goal_plan_outcomes.user_id",
                "goal_plan_outcomes.plan_run_id",
                "goal_plan_outcomes.id",
                "goal_plan_outcomes.goal_id",
            ],
            name="fk_goal_plan_allocations_owner_outcome",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "plan_run_id", "period_id"],
            [
                "goal_plan_periods.user_id",
                "goal_plan_periods.plan_run_id",
                "goal_plan_periods.id",
            ],
            name="fk_goal_plan_allocations_owner_period",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_plan_allocations")),
        sa.UniqueConstraint(
            "plan_run_id",
            "period_id",
            "outcome_id",
            name="uq_goal_plan_allocations_period_outcome",
        ),
    )
    op.create_index(
        "ix_goal_plan_allocations_user_run_period",
        "goal_plan_allocations",
        ["user_id", "plan_run_id", "period_id"],
        unique=False,
    )

    op.create_table(
        "goal_plan_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_run_id", sa.Uuid(), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("successor_plan_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('generated', 'approved', 'rejected', 'superseded')",
            name=op.f("ck_goal_plan_events_previous_status_allowed"),
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR length(trim(reason_code)) > 0",
            name=op.f("ck_goal_plan_events_reason_not_blank"),
        ),
        sa.CheckConstraint(
            "source IN ('system', 'user')",
            name=op.f("ck_goal_plan_events_source_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('generated', 'approved', 'rejected', 'superseded')",
            name=op.f("ck_goal_plan_events_status_allowed"),
        ),
        sa.CheckConstraint(
            "(status = 'generated' AND previous_status IS NULL AND "
            "source = 'system' AND successor_plan_id IS NULL) OR "
            "(status IN ('approved', 'rejected') AND "
            "previous_status = 'generated' AND source = 'user' AND "
            "successor_plan_id IS NULL) OR "
            "(status = 'superseded' AND previous_status IN "
            "('generated', 'approved') AND source = 'system' AND "
            "successor_plan_id IS NOT NULL)",
            name=op.f("ck_goal_plan_events_transition_shape_valid"),
        ),
        sa.CheckConstraint(
            "successor_plan_id IS NULL OR successor_plan_id <> plan_run_id",
            name=op.f("ck_goal_plan_events_successor_distinct"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "plan_run_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_events_owner_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "successor_plan_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_events_owner_successor",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_plan_events")),
    )
    op.create_index(
        "ix_goal_plan_events_user_run_occurred",
        "goal_plan_events",
        ["user_id", "plan_run_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "uq_goal_plan_events_generated_once",
        "goal_plan_events",
        ["plan_run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'generated'"),
    )
    op.create_index(
        "uq_goal_plan_events_decision_once",
        "goal_plan_events",
        ["plan_run_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('approved', 'rejected')"),
    )
    op.create_index(
        "uq_goal_plan_events_superseded_once",
        "goal_plan_events",
        ["plan_run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'superseded'"),
    )

    op.execute(
        """
        CREATE FUNCTION reject_goal_plan_record_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'goal plan records are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in (
        "goal_plan_runs",
        "goal_plan_outcomes",
        "goal_plan_periods",
        "goal_plan_allocations",
        "goal_plan_events",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_goal_plan_record_update()
            """
        )
    op.execute(
        """
        CREATE FUNCTION validate_goal_plan_event_transition()
        RETURNS trigger AS $$
        DECLARE
            latest_status text;
            latest_occurred_at timestamptz;
        BEGIN
            PERFORM 1
            FROM goal_plan_runs
            WHERE user_id = NEW.user_id AND id = NEW.plan_run_id
            FOR UPDATE;

            SELECT status, occurred_at
            INTO latest_status, latest_occurred_at
            FROM goal_plan_events
            WHERE user_id = NEW.user_id AND plan_run_id = NEW.plan_run_id
            ORDER BY occurred_at DESC, created_at DESC, id DESC
            LIMIT 1;

            IF latest_status IS NULL THEN
                IF NEW.status <> 'generated' OR NEW.previous_status IS NOT NULL THEN
                    RAISE EXCEPTION 'goal plan lifecycle must begin as generated';
                END IF;
            ELSE
                IF NEW.previous_status IS DISTINCT FROM latest_status THEN
                    RAISE EXCEPTION 'goal plan previous status is stale';
                END IF;
                IF latest_occurred_at > NEW.occurred_at THEN
                    RAISE EXCEPTION 'goal plan event timestamps must be chronological';
                END IF;
                IF NOT (
                    (latest_status = 'generated' AND NEW.status IN
                        ('approved', 'rejected', 'superseded')) OR
                    (latest_status = 'approved' AND NEW.status = 'superseded')
                ) THEN
                    RAISE EXCEPTION 'invalid goal plan lifecycle transition';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_goal_plan_events_transition
        BEFORE INSERT ON goal_plan_events
        FOR EACH ROW EXECUTE FUNCTION validate_goal_plan_event_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION require_goal_plan_generated_event()
        RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM goal_plan_events
                WHERE user_id = NEW.user_id
                  AND plan_run_id = NEW.id
                  AND status = 'generated'
            ) THEN
                RAISE EXCEPTION 'goal plan requires a generated lifecycle event';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_goal_plan_runs_generated_event
        AFTER INSERT ON goal_plan_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_goal_plan_generated_event()
        """
    )


def downgrade() -> None:
    """Remove goal-plan persistence and lifecycle functions."""
    op.execute(
        "DROP TRIGGER trg_goal_plan_runs_generated_event ON goal_plan_runs"
    )
    op.execute("DROP FUNCTION require_goal_plan_generated_event()")
    op.execute(
        "DROP TRIGGER trg_goal_plan_events_transition ON goal_plan_events"
    )
    op.execute("DROP FUNCTION validate_goal_plan_event_transition()")
    for table_name in (
        "goal_plan_events",
        "goal_plan_allocations",
        "goal_plan_periods",
        "goal_plan_outcomes",
        "goal_plan_runs",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION reject_goal_plan_record_update()")

    op.drop_index(
        "uq_goal_plan_events_superseded_once", table_name="goal_plan_events"
    )
    op.drop_index(
        "uq_goal_plan_events_decision_once", table_name="goal_plan_events"
    )
    op.drop_index(
        "uq_goal_plan_events_generated_once", table_name="goal_plan_events"
    )
    op.drop_index(
        "ix_goal_plan_events_user_run_occurred", table_name="goal_plan_events"
    )
    op.drop_table("goal_plan_events")
    op.drop_index(
        "ix_goal_plan_allocations_user_run_period",
        table_name="goal_plan_allocations",
    )
    op.drop_table("goal_plan_allocations")
    op.drop_index(
        "ix_goal_plan_periods_user_run_period", table_name="goal_plan_periods"
    )
    op.drop_table("goal_plan_periods")
    op.drop_index(
        "ix_goal_plan_outcomes_user_run_rank", table_name="goal_plan_outcomes"
    )
    op.drop_table("goal_plan_outcomes")
    op.drop_index(
        "ix_goal_plan_runs_user_currency_created", table_name="goal_plan_runs"
    )
    op.drop_index("ix_goal_plan_runs_user_created", table_name="goal_plan_runs")
    op.drop_table("goal_plan_runs")
