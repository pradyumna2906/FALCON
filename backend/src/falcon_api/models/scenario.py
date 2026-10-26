"""Immutable owner-scoped scenario runs, results, and selection history."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from falcon_api.infrastructure.persistence import (
    Base,
    CurrencyCode,
    MoneyAmount,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import (
    ScenarioSimulationEventSource,
    ScenarioSimulationEventType,
)


class ScenarioSimulationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store one immutable scenario decision set and its trusted provenance."""

    __tablename__ = "scenario_simulation_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_scenario_runs_user_id_id"),
        CheckConstraint(
            "snapshot_id ~ '^[0-9a-f]{64}$' AND "
            "analysis_id ~ '^[0-9a-f]{64}$' AND "
            "baseline_path_id ~ '^[0-9a-f]{64}$'",
            name="hashes_sha256_hex",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint(
            "(horizon_start IS NULL AND horizon_end IS NULL AND "
            "horizon_months = 0) OR (horizon_start IS NOT NULL AND "
            "horizon_end >= horizon_start AND horizon_months >= 1)",
            name="horizon_valid",
        ),
        CheckConstraint(
            "root_seed >= 0 AND root_seed <= 9223372036854775807 AND "
            "trial_count >= 1 AND trial_count <= 10000 AND "
            "horizon_months >= 0 AND horizon_months <= 24 AND "
            "scenario_count >= 4 AND scenario_count <= 13",
            name="execution_bounds_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(snapshot_warnings) = 'array' AND "
            "jsonb_typeof(reason_codes) = 'array'",
            name="evidence_arrays",
        ),
        ForeignKeyConstraint(
            ["user_id", "source_plan_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_scenario_runs_owner_source_plan",
        ),
        Index("ix_scenario_runs_user_created", "user_id", "created_at"),
        Index(
            "ix_scenario_runs_user_source_created",
            "user_id",
            "source_plan_id",
            "created_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_scenario_runs_user_id_users",
        ),
        nullable=False,
    )
    source_plan_id: Mapped[UUID] = mapped_column(nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_id: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_path_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[CurrencyCode] = mapped_column(nullable=False)
    cutoff_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    horizon_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    comparison_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitivity_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    persistence_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    monte_carlo_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    probability_method: Mapped[str] = mapped_column(String(64), nullable=False)
    percentile_method: Mapped[str] = mapped_column(String(64), nullable=False)
    root_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trial_count: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_months: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    definitions: Mapped[list[ScenarioDefinition]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScenarioDefinition.ordinal",
    )
    comparisons: Mapped[list[ScenarioComparison]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="(ScenarioComparison.user_id, ScenarioComparison.simulation_run_id)",
        order_by="ScenarioComparison.rank",
    )
    events: Mapped[list[ScenarioEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="(ScenarioEvent.user_id, ScenarioEvent.simulation_run_id)",
        order_by="ScenarioEvent.occurred_at, ScenarioEvent.created_at, ScenarioEvent.id",
    )

    @property
    def selected_scenario_id(self) -> UUID | None:
        """Return the latest append-only user selection, if one remains active."""
        for event in reversed(self.events):
            event_type = ScenarioSimulationEventType(event.event_type)
            if event_type is ScenarioSimulationEventType.SELECTED:
                return event.scenario_definition_id
            if event_type is ScenarioSimulationEventType.SELECTION_CLEARED:
                return None
        return None

    @property
    def selected_at(self) -> datetime | None:
        """Return when the current selection state was last changed."""
        for event in reversed(self.events):
            if ScenarioSimulationEventType(event.event_type) in {
                ScenarioSimulationEventType.SELECTED,
                ScenarioSimulationEventType.SELECTION_CLEARED,
            }:
                return event.occurred_at
        return None


class ScenarioDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Freeze one standard or user-defined alternative and aggregate results."""

    __tablename__ = "scenario_definitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id"],
            ["scenario_simulation_runs.user_id", "scenario_simulation_runs.id"],
            name="fk_scenario_definitions_owner_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "user_id",
            "simulation_run_id",
            "id",
            name="uq_scenario_definitions_owner_run_id",
        ),
        UniqueConstraint(
            "simulation_run_id",
            "path_id",
            name="uq_scenario_definitions_run_path",
        ),
        UniqueConstraint(
            "simulation_run_id",
            "ordinal",
            name="uq_scenario_definitions_run_ordinal",
        ),
        CheckConstraint(
            "path_id ~ '^[0-9a-f]{64}$' AND "
            "evaluation_id ~ '^[0-9a-f]{64}$' AND "
            "risk_id ~ '^[0-9a-f]{64}$' AND "
            "simulation_id ~ '^[0-9a-f]{64}$'",
            name="hashes_sha256_hex",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "kind IN ('protected', 'expected', 'upside', 'user_defined')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "evaluation_status IN ('optimized', 'guarded_fallback', "
            "'blocked', 'infeasible', 'unavailable')",
            name="evaluation_status_allowed",
        ),
        CheckConstraint(
            "risk_status IN ('available', 'limited', 'blocked', 'unavailable')",
            name="risk_status_allowed",
        ),
        CheckConstraint(
            "reliability IN ('normal', 'provisional', 'conservative', 'unavailable')",
            name="reliability_allowed",
        ),
        CheckConstraint(
            "emergency_reserve_amount >= 0 AND capacity_total >= 0 AND "
            "allocated_total >= 0 AND unallocated_total >= 0 AND "
            "allocated_total + unallocated_total = capacity_total AND "
            "weighted_funding_score >= 0",
            name="deterministic_values_valid",
        ),
        CheckConstraint(
            "(all_goals_completion_probability IS NULL OR "
            "(all_goals_completion_probability >= 0 AND "
            "all_goals_completion_probability <= 1)) AND "
            "(all_deadlines_met_probability IS NULL OR "
            "(all_deadlines_met_probability >= 0 AND "
            "all_deadlines_met_probability <= 1)) AND "
            "(reserve_coverage_probability IS NULL OR "
            "(reserve_coverage_probability >= 0 AND reserve_coverage_probability <= 1)) AND "
            "(negative_savings_probability IS NULL OR "
            "(negative_savings_probability >= 0 AND negative_savings_probability <= 1)) AND "
            "(constraint_feasibility_probability IS NULL OR "
            "(constraint_feasibility_probability >= 0 AND "
            "constraint_feasibility_probability <= 1))",
            name="probabilities_valid",
        ),
        CheckConstraint(
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
            name="risk_shape_valid",
        ),
        CheckConstraint(
            "(expected_capacity IS NULL OR expected_capacity >= 0) AND "
            "(expected_total_shortfall IS NULL OR expected_total_shortfall >= 0) AND "
            "(tail_expected_shortfall_90 IS NULL OR tail_expected_shortfall_90 >= 0) AND "
            "(robustness_score IS NULL OR "
            "(robustness_score >= 0 AND robustness_score <= 100))",
            name="risk_values_valid",
        ),
        CheckConstraint(
            "assumptions IS NULL OR jsonb_typeof(assumptions) = 'object'",
            name="assumptions_object",
        ),
        CheckConstraint(
            "jsonb_typeof(reason_codes) = 'array'",
            name="reason_codes_array",
        ),
        Index(
            "uq_scenario_definitions_run_name_ci",
            "simulation_run_id",
            func.lower(text("name")),
            unique=True,
        ),
        Index(
            "ix_scenario_definitions_user_run_ordinal",
            "user_id",
            "simulation_run_id",
            "ordinal",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    simulation_run_id: Mapped[UUID] = mapped_column(nullable=False)
    path_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_id: Mapped[str] = mapped_column(String(64), nullable=False)
    simulation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    risk_status: Mapped[str] = mapped_column(String(16), nullable=False)
    selected_band: Mapped[str] = mapped_column(String(16), nullable=False)
    reliability: Mapped[str] = mapped_column(String(16), nullable=False)
    assumptions: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    emergency_reserve_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    capacity_total: Mapped[MoneyAmount] = mapped_column(nullable=False)
    allocated_total: Mapped[MoneyAmount] = mapped_column(nullable=False)
    unallocated_total: Mapped[MoneyAmount] = mapped_column(nullable=False)
    weighted_funding_score: Mapped[Decimal] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=False
    )
    all_goals_completion_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    all_deadlines_met_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    reserve_coverage_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    negative_savings_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    constraint_feasibility_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    expected_capacity: Mapped[MoneyAmount | None] = mapped_column(nullable=True)
    expected_total_shortfall: Mapped[MoneyAmount | None] = mapped_column(nullable=True)
    tail_expected_shortfall_90: Mapped[MoneyAmount | None] = mapped_column(nullable=True)
    robustness_score: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 4, asdecimal=True), nullable=True
    )

    run: Mapped[ScenarioSimulationRun] = relationship(back_populates="definitions")
    periods: Mapped[list[ScenarioPeriod]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScenarioPeriod.period_start",
    )
    outcomes: Mapped[list[ScenarioGoalOutcome]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScenarioGoalOutcome.rank",
    )
    comparison: Mapped[ScenarioComparison | None] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        foreign_keys="ScenarioComparison.scenario_definition_id",
    )


class ScenarioPeriod(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Freeze one deterministic monthly capacity and aggregate allocation."""

    __tablename__ = "scenario_periods"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            [
                "scenario_definitions.user_id",
                "scenario_definitions.simulation_run_id",
                "scenario_definitions.id",
            ],
            name="fk_scenario_periods_owner_definition",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "simulation_run_id",
            "scenario_definition_id",
            "period_start",
            name="uq_scenario_periods_definition_period",
        ),
        CheckConstraint(
            "source_capacity >= 0 AND selected_capacity >= 0 AND "
            "allocated_amount >= 0 AND unallocated_amount >= 0 AND "
            "allocated_amount + unallocated_amount = selected_capacity",
            name="totals_valid",
        ),
        Index(
            "ix_scenario_periods_user_run_definition_period",
            "user_id",
            "simulation_run_id",
            "scenario_definition_id",
            "period_start",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    simulation_run_id: Mapped[UUID] = mapped_column(nullable=False)
    scenario_definition_id: Mapped[UUID] = mapped_column(nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    source_capacity: Mapped[MoneyAmount] = mapped_column(nullable=False)
    income_delta: Mapped[MoneyAmount] = mapped_column(nullable=False)
    expense_delta: Mapped[MoneyAmount] = mapped_column(nullable=False)
    one_time_expense: Mapped[MoneyAmount] = mapped_column(nullable=False)
    recurring_expense_delta: Mapped[MoneyAmount] = mapped_column(nullable=False)
    debt_payment_delta: Mapped[MoneyAmount] = mapped_column(nullable=False)
    raw_protected_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    raw_expected_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    raw_upside_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    selected_capacity: Mapped[MoneyAmount] = mapped_column(nullable=False)
    allocated_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    unallocated_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)

    definition: Mapped[ScenarioDefinition] = relationship(back_populates="periods")


class ScenarioGoalOutcome(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Freeze deterministic and empirical results for one goal alternative."""

    __tablename__ = "scenario_goal_outcomes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            [
                "scenario_definitions.user_id",
                "scenario_definitions.simulation_run_id",
                "scenario_definitions.id",
            ],
            name="fk_scenario_goal_outcomes_owner_definition",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "simulation_run_id",
            "scenario_definition_id",
            "goal_id",
            name="uq_scenario_goal_outcomes_definition_goal",
        ),
        CheckConstraint("rank > 0", name="rank_positive"),
        CheckConstraint(
            "allocated_amount >= 0 AND projected_remaining_amount >= 0 AND "
            "protected_shortfall >= 0 AND expected_shortfall >= 0 AND "
            "(empirical_expected_shortfall IS NULL OR "
            "empirical_expected_shortfall >= 0) AND "
            "(empirical_shortfall_p90 IS NULL OR empirical_shortfall_p90 >= 0)",
            name="money_values_valid",
        ),
        CheckConstraint(
            "(deterministic_completion_probability IS NULL OR "
            "(deterministic_completion_probability >= 0 AND "
            "deterministic_completion_probability <= 1)) AND "
            "(empirical_completion_probability IS NULL OR "
            "(empirical_completion_probability >= 0 AND "
            "empirical_completion_probability <= 1)) AND "
            "(deadline_met_probability IS NULL OR "
            "(deadline_met_probability >= 0 AND deadline_met_probability <= 1))",
            name="probabilities_valid",
        ),
        CheckConstraint(
            "completion_count >= 0 AND completion_denominator >= 0 AND "
            "deadline_met_count >= 0 AND deadline_denominator >= 0 AND "
            "completion_count <= completion_denominator AND "
            "deadline_met_count <= deadline_denominator",
            name="counts_valid",
        ),
        CheckConstraint(
            "(empirical_completion_probability IS NULL AND "
            "deadline_met_probability IS NULL AND completion_denominator = 0 AND "
            "deadline_denominator = 0 AND empirical_expected_shortfall IS NULL AND "
            "empirical_shortfall_p90 IS NULL) OR "
            "(empirical_completion_probability IS NOT NULL AND "
            "deadline_met_probability IS NOT NULL AND completion_denominator > 0 AND "
            "deadline_denominator > 0 AND empirical_expected_shortfall IS NOT NULL AND "
            "empirical_shortfall_p90 IS NOT NULL)",
            name="empirical_shape_valid",
        ),
        Index(
            "ix_scenario_goal_outcomes_user_run_definition_rank",
            "user_id",
            "simulation_run_id",
            "scenario_definition_id",
            "rank",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    simulation_run_id: Mapped[UUID] = mapped_column(nullable=False)
    scenario_definition_id: Mapped[UUID] = mapped_column(nullable=False)
    goal_id: Mapped[UUID] = mapped_column(nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    feasibility_state: Mapped[str] = mapped_column(String(24), nullable=False)
    deadline_risk: Mapped[str] = mapped_column(String(24), nullable=False)
    allocated_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    projected_remaining_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    protected_shortfall: Mapped[MoneyAmount] = mapped_column(nullable=False)
    expected_shortfall: Mapped[MoneyAmount] = mapped_column(nullable=False)
    deterministic_completion_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    empirical_completion_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    deadline_met_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    completion_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_met_count: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_period_p10: Mapped[date | None] = mapped_column(Date, nullable=True)
    completion_period_p50: Mapped[date | None] = mapped_column(Date, nullable=True)
    completion_period_p90: Mapped[date | None] = mapped_column(Date, nullable=True)
    empirical_expected_shortfall: Mapped[MoneyAmount | None] = mapped_column(
        nullable=True
    )
    empirical_shortfall_p90: Mapped[MoneyAmount | None] = mapped_column(
        nullable=True
    )
    deterministic_deadline_met: Mapped[bool] = mapped_column(Boolean, nullable=False)

    definition: Mapped[ScenarioDefinition] = relationship(back_populates="outcomes")


class ScenarioComparison(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist one ranked baseline comparison and bounded sensitivity evidence."""

    __tablename__ = "scenario_comparisons"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id"],
            ["scenario_simulation_runs.user_id", "scenario_simulation_runs.id"],
            name="fk_scenario_comparisons_owner_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            [
                "scenario_definitions.user_id",
                "scenario_definitions.simulation_run_id",
                "scenario_definitions.id",
            ],
            name="fk_scenario_comparisons_owner_definition",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "baseline_definition_id"],
            [
                "scenario_definitions.user_id",
                "scenario_definitions.simulation_run_id",
                "scenario_definitions.id",
            ],
            name="fk_scenario_comparisons_owner_baseline",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "dominated_by_definition_id"],
            [
                "scenario_definitions.user_id",
                "scenario_definitions.simulation_run_id",
                "scenario_definitions.id",
            ],
            name="fk_scenario_comparisons_owner_dominator",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "simulation_run_id",
            "scenario_definition_id",
            name="uq_scenario_comparisons_run_definition",
        ),
        UniqueConstraint(
            "simulation_run_id",
            "rank",
            name="uq_scenario_comparisons_run_rank",
        ),
        CheckConstraint(
            "comparison_hash ~ '^[0-9a-f]{64}$'",
            name="hash_sha256_hex",
        ),
        CheckConstraint(
            "rank > 0 AND decision_score >= 0 AND decision_score <= 100 AND "
            "additional_required_contribution >= 0",
            name="ranking_values_valid",
        ),
        CheckConstraint(
            "NOT recommended OR dominated_by_definition_id IS NULL",
            name="recommendation_not_dominated",
        ),
        CheckConstraint(
            "jsonb_typeof(sensitivity_signals) = 'array' AND "
            "jsonb_typeof(reason_codes) = 'array'",
            name="evidence_arrays",
        ),
        Index(
            "ix_scenario_comparisons_user_run_rank",
            "user_id",
            "simulation_run_id",
            "rank",
        ),
        Index(
            "uq_scenario_comparisons_recommended_once",
            "simulation_run_id",
            unique=True,
            postgresql_where=text("recommended"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    simulation_run_id: Mapped[UUID] = mapped_column(nullable=False)
    scenario_definition_id: Mapped[UUID] = mapped_column(nullable=False)
    baseline_definition_id: Mapped[UUID] = mapped_column(nullable=False)
    dominated_by_definition_id: Mapped[UUID | None] = mapped_column(nullable=True)
    comparison_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_capacity_delta: Mapped[MoneyAmount | None] = mapped_column(nullable=True)
    completion_probability_delta: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    deadline_probability_delta: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    reserve_probability_delta: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    negative_savings_probability_delta: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    expected_shortfall_delta: Mapped[MoneyAmount | None] = mapped_column(nullable=True)
    tail_shortfall_delta: Mapped[MoneyAmount | None] = mapped_column(nullable=True)
    robustness_delta: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 4, asdecimal=True), nullable=True
    )
    weighted_funding_delta: Mapped[Decimal] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=False
    )
    fully_funded_goal_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_met_goal_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    additional_required_contribution: Mapped[MoneyAmount] = mapped_column(nullable=False)
    decision_score: Mapped[Decimal] = mapped_column(
        Numeric(9, 4, asdecimal=True), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sensitivity_signals: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    run: Mapped[ScenarioSimulationRun] = relationship(
        back_populates="comparisons",
        foreign_keys=[user_id, simulation_run_id],
    )
    definition: Mapped[ScenarioDefinition] = relationship(
        back_populates="comparison",
        foreign_keys=[scenario_definition_id],
    )


class ScenarioEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only generation and user-selection history."""

    __tablename__ = "scenario_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id"],
            ["scenario_simulation_runs.user_id", "scenario_simulation_runs.id"],
            name="fk_scenario_events_owner_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "simulation_run_id", "scenario_definition_id"],
            [
                "scenario_definitions.user_id",
                "scenario_definitions.simulation_run_id",
                "scenario_definitions.id",
            ],
            name="fk_scenario_events_owner_definition",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "event_type IN ('generated', 'selected', 'selection_cleared')",
            name="event_type_allowed",
        ),
        CheckConstraint(
            "source IN ('system', 'user')",
            name="source_allowed",
        ),
        CheckConstraint(
            "(event_type = 'generated' AND source = 'system' AND "
            "scenario_definition_id IS NULL) OR "
            "(event_type = 'selected' AND source = 'user' AND "
            "scenario_definition_id IS NOT NULL) OR "
            "(event_type = 'selection_cleared' AND source = 'user' AND "
            "scenario_definition_id IS NULL)",
            name="event_shape_valid",
        ),
        CheckConstraint(
            "reason_code IS NULL OR length(trim(reason_code)) > 0",
            name="reason_not_blank",
        ),
        Index(
            "ix_scenario_events_user_run_occurred",
            "user_id",
            "simulation_run_id",
            "occurred_at",
        ),
        Index(
            "uq_scenario_events_generated_once",
            "simulation_run_id",
            unique=True,
            postgresql_where=text("event_type = 'generated'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    simulation_run_id: Mapped[UUID] = mapped_column(nullable=False)
    scenario_definition_id: Mapped[UUID | None] = mapped_column(nullable=True)
    event_type: Mapped[ScenarioSimulationEventType] = mapped_column(
        String(24), nullable=False
    )
    source: Mapped[ScenarioSimulationEventSource] = mapped_column(
        String(16), nullable=False
    )
    occurred_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    run: Mapped[ScenarioSimulationRun] = relationship(
        back_populates="events",
        foreign_keys=[user_id, simulation_run_id],
    )
