"""Add immutable owner-scoped scenario simulation persistence.

Revision ID: c4d7a9e2f816
Revises: b3e8f6c2d715
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c4d7a9e2f816"
down_revision: str | Sequence[str] | None = "b3e8f6c2d715"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    """Install immutable simulations and append-only selection history."""
    op.create_table(
        "scenario_simulation_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_plan_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("analysis_id", sa.String(length=64), nullable=False),
        sa.Column("baseline_path_id", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("horizon_start", sa.Date(), nullable=True),
        sa.Column("horizon_end", sa.Date(), nullable=True),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("comparison_policy_version", sa.String(length=32), nullable=False),
        sa.Column("sensitivity_policy_version", sa.String(length=32), nullable=False),
        sa.Column("decision_policy_version", sa.String(length=32), nullable=False),
        sa.Column("persistence_policy_version", sa.String(length=32), nullable=False),
        sa.Column("monte_carlo_policy_version", sa.String(length=32), nullable=False),
        sa.Column("risk_policy_version", sa.String(length=32), nullable=False),
        sa.Column("probability_method", sa.String(length=64), nullable=False),
        sa.Column("percentile_method", sa.String(length=64), nullable=False),
        sa.Column("root_seed", sa.BigInteger(), nullable=False),
        sa.Column("trial_count", sa.Integer(), nullable=False),
        sa.Column("horizon_months", sa.Integer(), nullable=False),
        sa.Column("scenario_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_warnings", postgresql.JSONB(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "snapshot_id ~ '^[0-9a-f]{64}$' AND "
            "analysis_id ~ '^[0-9a-f]{64}$' AND "
            "baseline_path_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_scenario_simulation_runs_hashes_sha256_hex"),
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_scenario_simulation_runs_currency_iso"),
        ),
        sa.CheckConstraint(
            "(horizon_start IS NULL AND horizon_end IS NULL AND "
            "horizon_months = 0) OR (horizon_start IS NOT NULL AND "
            "horizon_end >= horizon_start AND horizon_months >= 1)",
            name=op.f("ck_scenario_simulation_runs_horizon_valid"),
        ),
        sa.CheckConstraint(
            "root_seed >= 0 AND root_seed <= 9223372036854775807 AND "
            "trial_count >= 1 AND trial_count <= 10000 AND "
            "horizon_months >= 0 AND horizon_months <= 24 AND "
            "scenario_count >= 4 AND scenario_count <= 13",
            name=op.f("ck_scenario_simulation_runs_execution_bounds_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot_warnings) = 'array' AND "
            "jsonb_typeof(reason_codes) = 'array'",
            name=op.f("ck_scenario_simulation_runs_evidence_arrays"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_scenario_runs_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "source_plan_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_scenario_runs_owner_source_plan",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_simulation_runs")),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_scenario_runs_user_id_id"
        ),
    )
    op.create_index(
        "ix_scenario_runs_user_created",
        "scenario_simulation_runs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_scenario_runs_user_source_created",
        "scenario_simulation_runs",
        ["user_id", "source_plan_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "scenario_definitions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("simulation_run_id", sa.Uuid(), nullable=False),
        sa.Column("path_id", sa.String(length=64), nullable=False),
        sa.Column("evaluation_id", sa.String(length=64), nullable=False),
        sa.Column("risk_id", sa.String(length=64), nullable=False),
        sa.Column("simulation_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("evaluation_status", sa.String(length=24), nullable=False),
        sa.Column("risk_status", sa.String(length=16), nullable=False),
        sa.Column("selected_band", sa.String(length=16), nullable=False),
        sa.Column("reliability", sa.String(length=16), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), nullable=True),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("emergency_reserve_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("capacity_total", sa.Numeric(19, 4), nullable=False),
        sa.Column("allocated_total", sa.Numeric(19, 4), nullable=False),
        sa.Column("unallocated_total", sa.Numeric(19, 4), nullable=False),
        sa.Column("weighted_funding_score", sa.Numeric(20, 6), nullable=False),
        sa.Column("all_goals_completion_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("all_deadlines_met_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("reserve_coverage_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("negative_savings_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("constraint_feasibility_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("expected_capacity", sa.Numeric(19, 4), nullable=True),
        sa.Column("expected_total_shortfall", sa.Numeric(19, 4), nullable=True),
        sa.Column("tail_expected_shortfall_90", sa.Numeric(19, 4), nullable=True),
        sa.Column("robustness_score", sa.Numeric(9, 4), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "path_id ~ '^[0-9a-f]{64}$' AND "
            "evaluation_id ~ '^[0-9a-f]{64}$' AND "
            "risk_id ~ '^[0-9a-f]{64}$' AND "
            "simulation_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_scenario_definitions_hashes_sha256_hex"),
        ),
        sa.CheckConstraint(
            "ordinal > 0",
            name=op.f("ck_scenario_definitions_ordinal_positive"),
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name=op.f("ck_scenario_definitions_name_not_blank"),
        ),
        sa.CheckConstraint(
            "kind IN ('protected', 'expected', 'upside', 'user_defined')",
            name=op.f("ck_scenario_definitions_kind_allowed"),
        ),
        sa.CheckConstraint(
            "evaluation_status IN ('optimized', 'guarded_fallback', "
            "'blocked', 'infeasible', 'unavailable')",
            name=op.f("ck_scenario_definitions_evaluation_status_allowed"),
        ),
        sa.CheckConstraint(
            "risk_status IN ('available', 'limited', 'blocked', 'unavailable')",
            name=op.f("ck_scenario_definitions_risk_status_allowed"),
        ),
        sa.CheckConstraint(
            "reliability IN ('normal', 'provisional', 'conservative', 'unavailable')",
            name=op.f("ck_scenario_definitions_reliability_allowed"),
        ),
        sa.CheckConstraint(
            "emergency_reserve_amount >= 0 AND capacity_total >= 0 AND "
            "allocated_total >= 0 AND unallocated_total >= 0 AND "
            "allocated_total + unallocated_total = capacity_total AND "
            "weighted_funding_score >= 0",
            name=op.f("ck_scenario_definitions_deterministic_values_valid"),
        ),
        sa.CheckConstraint(
            "(all_goals_completion_probability IS NULL OR "
            "(all_goals_completion_probability >= 0 AND all_goals_completion_probability <= 1)) AND "
            "(all_deadlines_met_probability IS NULL OR "
            "(all_deadlines_met_probability >= 0 AND all_deadlines_met_probability <= 1)) AND "
            "(reserve_coverage_probability IS NULL OR "
            "(reserve_coverage_probability >= 0 AND reserve_coverage_probability <= 1)) AND "
            "(negative_savings_probability IS NULL OR "
            "(negative_savings_probability >= 0 AND negative_savings_probability <= 1)) AND "
            "(constraint_feasibility_probability IS NULL OR "
            "(constraint_feasibility_probability >= 0 AND "
            "constraint_feasibility_probability <= 1))",
            name=op.f("ck_scenario_definitions_probabilities_valid"),
        ),
        sa.CheckConstraint(
            "(risk_status IN ('available', 'limited') AND "
            "all_goals_completion_probability IS NOT NULL AND "
            "all_deadlines_met_probability IS NOT NULL AND "
            "reserve_coverage_probability IS NOT NULL AND "
            "negative_savings_probability IS NOT NULL AND "
            "constraint_feasibility_probability IS NOT NULL AND "
            "expected_capacity IS NOT NULL AND expected_total_shortfall IS NOT NULL AND "
            "tail_expected_shortfall_90 IS NOT NULL AND robustness_score IS NOT NULL) OR "
            "(risk_status IN ('blocked', 'unavailable') AND "
            "all_goals_completion_probability IS NULL AND "
            "all_deadlines_met_probability IS NULL AND "
            "reserve_coverage_probability IS NULL AND "
            "negative_savings_probability IS NULL AND "
            "constraint_feasibility_probability IS NULL AND "
            "expected_capacity IS NULL AND expected_total_shortfall IS NULL AND "
            "tail_expected_shortfall_90 IS NULL AND robustness_score IS NULL)",
            name=op.f("ck_scenario_definitions_risk_shape_valid"),
        ),
        sa.CheckConstraint(
            "(expected_capacity IS NULL OR expected_capacity >= 0) AND "
            "(expected_total_shortfall IS NULL OR expected_total_shortfall >= 0) AND "
            "(tail_expected_shortfall_90 IS NULL OR tail_expected_shortfall_90 >= 0) AND "
            "(robustness_score IS NULL OR "
            "(robustness_score >= 0 AND robustness_score <= 100))",
            name=op.f("ck_scenario_definitions_risk_values_valid"),
        ),
        sa.CheckConstraint(
            "assumptions IS NULL OR jsonb_typeof(assumptions) = 'object'",
            name=op.f("ck_scenario_definitions_assumptions_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reason_codes) = 'array'",
            name=op.f("ck_scenario_definitions_reason_codes_array"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id"],
            ["scenario_simulation_runs.user_id", "scenario_simulation_runs.id"],
            name="fk_scenario_definitions_owner_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_definitions")),
        sa.UniqueConstraint(
            "user_id", "simulation_run_id", "id",
            name="uq_scenario_definitions_owner_run_id",
        ),
        sa.UniqueConstraint(
            "simulation_run_id", "path_id",
            name="uq_scenario_definitions_run_path",
        ),
        sa.UniqueConstraint(
            "simulation_run_id", "ordinal",
            name="uq_scenario_definitions_run_ordinal",
        ),
    )
    op.create_index(
        "uq_scenario_definitions_run_name_ci",
        "scenario_definitions",
        ["simulation_run_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "ix_scenario_definitions_user_run_ordinal",
        "scenario_definitions",
        ["user_id", "simulation_run_id", "ordinal"],
        unique=False,
    )

    op.create_table(
        "scenario_periods",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("simulation_run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_definition_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("source_capacity", sa.Numeric(19, 4), nullable=False),
        sa.Column("income_delta", sa.Numeric(19, 4), nullable=False),
        sa.Column("expense_delta", sa.Numeric(19, 4), nullable=False),
        sa.Column("one_time_expense", sa.Numeric(19, 4), nullable=False),
        sa.Column("recurring_expense_delta", sa.Numeric(19, 4), nullable=False),
        sa.Column("debt_payment_delta", sa.Numeric(19, 4), nullable=False),
        sa.Column("raw_protected_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("raw_expected_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("raw_upside_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("selected_capacity", sa.Numeric(19, 4), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("unallocated_amount", sa.Numeric(19, 4), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "source_capacity >= 0 AND selected_capacity >= 0 AND "
            "allocated_amount >= 0 AND unallocated_amount >= 0 AND "
            "allocated_amount + unallocated_amount = selected_capacity",
            name=op.f("ck_scenario_periods_totals_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            ["scenario_definitions.user_id", "scenario_definitions.simulation_run_id", "scenario_definitions.id"],
            name="fk_scenario_periods_owner_definition",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_periods")),
        sa.UniqueConstraint(
            "simulation_run_id", "scenario_definition_id", "period_start",
            name="uq_scenario_periods_definition_period",
        ),
    )
    op.create_index(
        "ix_scenario_periods_user_run_definition_period",
        "scenario_periods",
        ["user_id", "simulation_run_id", "scenario_definition_id", "period_start"],
        unique=False,
    )

    op.create_table(
        "scenario_goal_outcomes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("simulation_run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_definition_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("feasibility_state", sa.String(length=24), nullable=False),
        sa.Column("deadline_risk", sa.String(length=24), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("projected_remaining_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("protected_shortfall", sa.Numeric(19, 4), nullable=False),
        sa.Column("expected_shortfall", sa.Numeric(19, 4), nullable=False),
        sa.Column("deterministic_completion_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("empirical_completion_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("deadline_met_probability", sa.Numeric(9, 6), nullable=True),
        sa.Column("completion_count", sa.Integer(), nullable=False),
        sa.Column("completion_denominator", sa.Integer(), nullable=False),
        sa.Column("deadline_met_count", sa.Integer(), nullable=False),
        sa.Column("deadline_denominator", sa.Integer(), nullable=False),
        sa.Column("completion_period_p10", sa.Date(), nullable=True),
        sa.Column("completion_period_p50", sa.Date(), nullable=True),
        sa.Column("completion_period_p90", sa.Date(), nullable=True),
        sa.Column("empirical_expected_shortfall", sa.Numeric(19, 4), nullable=True),
        sa.Column("empirical_shortfall_p90", sa.Numeric(19, 4), nullable=True),
        sa.Column("deterministic_deadline_met", sa.Boolean(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "rank > 0",
            name=op.f("ck_scenario_goal_outcomes_rank_positive"),
        ),
        sa.CheckConstraint(
            "allocated_amount >= 0 AND projected_remaining_amount >= 0 AND "
            "protected_shortfall >= 0 AND expected_shortfall >= 0 AND "
            "(empirical_expected_shortfall IS NULL OR empirical_expected_shortfall >= 0) AND "
            "(empirical_shortfall_p90 IS NULL OR empirical_shortfall_p90 >= 0)",
            name=op.f("ck_scenario_goal_outcomes_money_values_valid"),
        ),
        sa.CheckConstraint(
            "(deterministic_completion_probability IS NULL OR "
            "(deterministic_completion_probability >= 0 AND deterministic_completion_probability <= 1)) AND "
            "(empirical_completion_probability IS NULL OR "
            "(empirical_completion_probability >= 0 AND empirical_completion_probability <= 1)) AND "
            "(deadline_met_probability IS NULL OR "
            "(deadline_met_probability >= 0 AND deadline_met_probability <= 1))",
            name=op.f("ck_scenario_goal_outcomes_probabilities_valid"),
        ),
        sa.CheckConstraint(
            "completion_count >= 0 AND completion_denominator >= 0 AND "
            "deadline_met_count >= 0 AND deadline_denominator >= 0 AND "
            "completion_count <= completion_denominator AND "
            "deadline_met_count <= deadline_denominator",
            name=op.f("ck_scenario_goal_outcomes_counts_valid"),
        ),
        sa.CheckConstraint(
            "(empirical_completion_probability IS NULL AND "
            "deadline_met_probability IS NULL AND completion_denominator = 0 AND "
            "deadline_denominator = 0 AND empirical_expected_shortfall IS NULL AND "
            "empirical_shortfall_p90 IS NULL) OR "
            "(empirical_completion_probability IS NOT NULL AND "
            "deadline_met_probability IS NOT NULL AND completion_denominator > 0 AND "
            "deadline_denominator > 0 AND empirical_expected_shortfall IS NOT NULL AND "
            "empirical_shortfall_p90 IS NOT NULL)",
            name=op.f("ck_scenario_goal_outcomes_empirical_shape_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            ["scenario_definitions.user_id", "scenario_definitions.simulation_run_id", "scenario_definitions.id"],
            name="fk_scenario_goal_outcomes_owner_definition",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_goal_outcomes")),
        sa.UniqueConstraint(
            "simulation_run_id", "scenario_definition_id", "goal_id",
            name="uq_scenario_goal_outcomes_definition_goal",
        ),
    )
    op.create_index(
        "ix_scenario_goal_outcomes_user_run_definition_rank",
        "scenario_goal_outcomes",
        ["user_id", "simulation_run_id", "scenario_definition_id", "rank"],
        unique=False,
    )

    op.create_table(
        "scenario_comparisons",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("simulation_run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_definition_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_definition_id", sa.Uuid(), nullable=False),
        sa.Column("dominated_by_definition_id", sa.Uuid(), nullable=True),
        sa.Column("comparison_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_capacity_delta", sa.Numeric(19, 4), nullable=True),
        sa.Column("completion_probability_delta", sa.Numeric(9, 6), nullable=True),
        sa.Column("deadline_probability_delta", sa.Numeric(9, 6), nullable=True),
        sa.Column("reserve_probability_delta", sa.Numeric(9, 6), nullable=True),
        sa.Column("negative_savings_probability_delta", sa.Numeric(9, 6), nullable=True),
        sa.Column("expected_shortfall_delta", sa.Numeric(19, 4), nullable=True),
        sa.Column("tail_shortfall_delta", sa.Numeric(19, 4), nullable=True),
        sa.Column("robustness_delta", sa.Numeric(9, 4), nullable=True),
        sa.Column("weighted_funding_delta", sa.Numeric(20, 6), nullable=False),
        sa.Column("fully_funded_goal_delta", sa.Integer(), nullable=False),
        sa.Column("deadline_met_goal_delta", sa.Integer(), nullable=False),
        sa.Column("additional_required_contribution", sa.Numeric(19, 4), nullable=False),
        sa.Column("decision_score", sa.Numeric(9, 4), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("recommended", sa.Boolean(), nullable=False),
        sa.Column("sensitivity_signals", postgresql.JSONB(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "comparison_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_scenario_comparisons_hash_sha256_hex"),
        ),
        sa.CheckConstraint(
            "rank > 0 AND decision_score >= 0 AND decision_score <= 100 AND "
            "additional_required_contribution >= 0",
            name=op.f("ck_scenario_comparisons_ranking_values_valid"),
        ),
        sa.CheckConstraint(
            "NOT recommended OR dominated_by_definition_id IS NULL",
            name=op.f("ck_scenario_comparisons_recommendation_not_dominated"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(sensitivity_signals) = 'array' AND "
            "jsonb_typeof(reason_codes) = 'array'",
            name=op.f("ck_scenario_comparisons_evidence_arrays"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id"],
            ["scenario_simulation_runs.user_id", "scenario_simulation_runs.id"],
            name="fk_scenario_comparisons_owner_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            ["scenario_definitions.user_id", "scenario_definitions.simulation_run_id", "scenario_definitions.id"],
            name="fk_scenario_comparisons_owner_definition",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "baseline_definition_id"],
            ["scenario_definitions.user_id", "scenario_definitions.simulation_run_id", "scenario_definitions.id"],
            name="fk_scenario_comparisons_owner_baseline",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "dominated_by_definition_id"],
            ["scenario_definitions.user_id", "scenario_definitions.simulation_run_id", "scenario_definitions.id"],
            name="fk_scenario_comparisons_owner_dominator",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_comparisons")),
        sa.UniqueConstraint(
            "simulation_run_id", "scenario_definition_id",
            name="uq_scenario_comparisons_run_definition",
        ),
        sa.UniqueConstraint(
            "simulation_run_id", "rank",
            name="uq_scenario_comparisons_run_rank",
        ),
    )
    op.create_index(
        "ix_scenario_comparisons_user_run_rank",
        "scenario_comparisons",
        ["user_id", "simulation_run_id", "rank"],
        unique=False,
    )
    op.create_index(
        "uq_scenario_comparisons_recommended_once",
        "scenario_comparisons",
        ["simulation_run_id"],
        unique=True,
        postgresql_where=sa.text("recommended"),
    )

    op.create_table(
        "scenario_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("simulation_run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_definition_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "event_type IN ('generated', 'selected', 'selection_cleared')",
            name=op.f("ck_scenario_events_event_type_allowed"),
        ),
        sa.CheckConstraint(
            "source IN ('system', 'user')",
            name=op.f("ck_scenario_events_source_allowed"),
        ),
        sa.CheckConstraint(
            "(event_type = 'generated' AND source = 'system' AND "
            "scenario_definition_id IS NULL) OR "
            "(event_type = 'selected' AND source = 'user' AND "
            "scenario_definition_id IS NOT NULL) OR "
            "(event_type = 'selection_cleared' AND source = 'user' AND "
            "scenario_definition_id IS NULL)",
            name=op.f("ck_scenario_events_event_shape_valid"),
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR length(trim(reason_code)) > 0",
            name=op.f("ck_scenario_events_reason_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id"],
            ["scenario_simulation_runs.user_id", "scenario_simulation_runs.id"],
            name="fk_scenario_events_owner_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            ["scenario_definitions.user_id", "scenario_definitions.simulation_run_id", "scenario_definitions.id"],
            name="fk_scenario_events_owner_definition",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_events")),
    )
    op.create_index(
        "ix_scenario_events_user_run_occurred",
        "scenario_events",
        ["user_id", "simulation_run_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "uq_scenario_events_generated_once",
        "scenario_events",
        ["simulation_run_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'generated'"),
    )

    op.execute(
        """
        CREATE FUNCTION reject_scenario_record_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'scenario simulation records are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in (
        "scenario_simulation_runs",
        "scenario_definitions",
        "scenario_periods",
        "scenario_goal_outcomes",
        "scenario_comparisons",
        "scenario_events",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_scenario_record_update()
            """
        )
    op.execute(
        """
        CREATE FUNCTION validate_scenario_event_transition()
        RETURNS trigger AS $$
        DECLARE
            latest_type text;
            latest_occurred_at timestamptz;
        BEGIN
            PERFORM 1
            FROM scenario_simulation_runs
            WHERE user_id = NEW.user_id AND id = NEW.simulation_run_id
            FOR UPDATE;

            SELECT event_type, occurred_at
            INTO latest_type, latest_occurred_at
            FROM scenario_events
            WHERE user_id = NEW.user_id
              AND simulation_run_id = NEW.simulation_run_id
            ORDER BY occurred_at DESC, created_at DESC, id DESC
            LIMIT 1;

            IF latest_type IS NULL THEN
                IF NEW.event_type <> 'generated' THEN
                    RAISE EXCEPTION 'scenario history must begin as generated';
                END IF;
            ELSE
                IF NEW.event_type = 'generated' THEN
                    RAISE EXCEPTION 'scenario generated event already exists';
                END IF;
                IF latest_occurred_at > NEW.occurred_at THEN
                    RAISE EXCEPTION 'scenario event timestamps must be chronological';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_scenario_events_transition
        BEFORE INSERT ON scenario_events
        FOR EACH ROW EXECUTE FUNCTION validate_scenario_event_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION require_scenario_generated_event()
        RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM scenario_events
                WHERE user_id = NEW.user_id
                  AND simulation_run_id = NEW.id
                  AND event_type = 'generated'
            ) THEN
                RAISE EXCEPTION 'scenario run requires a generated history event';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_scenario_runs_generated_event
        AFTER INSERT ON scenario_simulation_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_scenario_generated_event()
        """
    )


def downgrade() -> None:
    """Remove scenario persistence and append-only history functions."""
    op.execute(
        "DROP TRIGGER trg_scenario_runs_generated_event "
        "ON scenario_simulation_runs"
    )
    op.execute("DROP FUNCTION require_scenario_generated_event()")
    op.execute("DROP TRIGGER trg_scenario_events_transition ON scenario_events")
    op.execute("DROP FUNCTION validate_scenario_event_transition()")
    for table_name in (
        "scenario_events",
        "scenario_comparisons",
        "scenario_goal_outcomes",
        "scenario_periods",
        "scenario_definitions",
        "scenario_simulation_runs",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION reject_scenario_record_update()")

    op.drop_index("uq_scenario_events_generated_once", table_name="scenario_events")
    op.drop_index("ix_scenario_events_user_run_occurred", table_name="scenario_events")
    op.drop_table("scenario_events")
    op.drop_index(
        "uq_scenario_comparisons_recommended_once",
        table_name="scenario_comparisons",
    )
    op.drop_index(
        "ix_scenario_comparisons_user_run_rank",
        table_name="scenario_comparisons",
    )
    op.drop_table("scenario_comparisons")
    op.drop_index(
        "ix_scenario_goal_outcomes_user_run_definition_rank",
        table_name="scenario_goal_outcomes",
    )
    op.drop_table("scenario_goal_outcomes")
    op.drop_index(
        "ix_scenario_periods_user_run_definition_period",
        table_name="scenario_periods",
    )
    op.drop_table("scenario_periods")
    op.drop_index(
        "ix_scenario_definitions_user_run_ordinal",
        table_name="scenario_definitions",
    )
    op.drop_index(
        "uq_scenario_definitions_run_name_ci",
        table_name="scenario_definitions",
    )
    op.drop_table("scenario_definitions")
    op.drop_index(
        "ix_scenario_runs_user_source_created",
        table_name="scenario_simulation_runs",
    )
    op.drop_index(
        "ix_scenario_runs_user_created",
        table_name="scenario_simulation_runs",
    )
    op.drop_table("scenario_simulation_runs")
