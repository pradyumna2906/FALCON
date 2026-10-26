"""Immutable owner-scoped goal-plan runs, schedules, and lifecycle history."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
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
from falcon_api.models.enums import GoalPlanEventSource, GoalPlanStatus


class GoalPlanRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store one immutable optimization decision and its policy provenance."""

    __tablename__ = "goal_plan_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_goal_plan_runs_user_id_id"),
        CheckConstraint(
            "snapshot_id ~ '^[0-9a-f]{64}$' AND "
            "deterministic_plan_id ~ '^[0-9a-f]{64}$'",
            name="hashes_sha256_hex",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint(
            "(horizon_start IS NULL AND horizon_end IS NULL) OR "
            "(horizon_start IS NOT NULL AND horizon_end >= horizon_start)",
            name="horizon_valid",
        ),
        CheckConstraint(
            "strategy IN ('optimized', 'guarded_greedy_fallback', 'blocked')",
            name="strategy_allowed",
        ),
        CheckConstraint(
            "optimizer_status IS NULL OR optimizer_status IN "
            "('optimal', 'no_solution', 'solver_unavailable', "
            "'solver_failed', 'invalid_solution')",
            name="optimizer_status_allowed",
        ),
        CheckConstraint(
            "overall_feasibility IN "
            "('fully_funded', 'feasible', 'at_risk', 'uncertain', "
            "'blocked', 'unavailable')",
            name="overall_feasibility_allowed",
        ),
        CheckConstraint(
            "goal_count >= 0 AND feasible_goal_count >= 0 AND "
            "at_risk_goal_count >= 0 AND uncertain_goal_count >= 0 AND "
            "fully_funded_goal_count >= 0 AND deadline_met_goal_count >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint(
            "feasible_goal_count + at_risk_goal_count + uncertain_goal_count "
            "= goal_count",
            name="assessment_counts_reconcile",
        ),
        CheckConstraint(
            "fully_funded_goal_count <= goal_count AND "
            "deadline_met_goal_count <= goal_count",
            name="outcome_counts_bounded",
        ),
        CheckConstraint(
            "emergency_reserve_amount >= 0 AND available_savings >= 0 AND "
            "allocated_savings >= 0 AND unallocated_savings >= 0 AND "
            "allocated_savings + unallocated_savings = available_savings",
            name="money_totals_valid",
        ),
        CheckConstraint(
            "weighted_funding_score >= 0 AND "
            "greedy_weighted_funding_score >= 0 AND "
            "guarded_fallback_weighted_funding_score >= 0 AND "
            "(optimized_weighted_funding_score IS NULL OR "
            "optimized_weighted_funding_score >= 0)",
            name="scores_non_negative",
        ),
        CheckConstraint(
            "jsonb_typeof(assumptions) = 'array' AND "
            "jsonb_typeof(reason_codes) = 'array' AND "
            "jsonb_typeof(snapshot_warnings) = 'array' AND "
            "jsonb_typeof(guardrail_reason_codes) = 'array'",
            name="evidence_arrays",
        ),
        Index(
            "ix_goal_plan_runs_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_goal_plan_runs_user_currency_created",
            "user_id",
            "currency",
            "created_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_goal_plan_runs_user_id_users",
        ),
        nullable=False,
    )
    predecessor_plan_id: Mapped[UUID | None] = mapped_column(nullable=True)
    forecast_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    deterministic_plan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[CurrencyCode] = mapped_column(nullable=False)
    planning_cutoff_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    horizon_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    capacity_policy_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    feasibility_policy_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    ranking_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    greedy_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    optimization_policy_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    guardrail_policy_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    optimizer_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    overall_feasibility: Mapped[str] = mapped_column(String(24), nullable=False)
    solver_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    solver_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allocation_band: Mapped[str] = mapped_column(String(64), nullable=False)
    forecast_reliability: Mapped[str] = mapped_column(String(24), nullable=False)
    emergency_reserve_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    available_savings: Mapped[MoneyAmount] = mapped_column(nullable=False)
    allocated_savings: Mapped[MoneyAmount] = mapped_column(nullable=False)
    unallocated_savings: Mapped[MoneyAmount] = mapped_column(nullable=False)
    weighted_funding_score: Mapped[Decimal] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=False
    )
    greedy_weighted_funding_score: Mapped[Decimal] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=False
    )
    guarded_fallback_weighted_funding_score: Mapped[Decimal] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=False
    )
    optimized_weighted_funding_score: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    selected_score_delta_from_greedy: Mapped[Decimal] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=False
    )
    goal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    feasible_goal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    at_risk_goal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uncertain_goal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fully_funded_goal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_met_goal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    snapshot_warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    guardrail_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    __table_args__ += (
        ForeignKeyConstraint(
            ["user_id", "predecessor_plan_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_runs_owner_predecessor",
        ),
        ForeignKeyConstraint(
            ["user_id", "forecast_run_id"],
            ["forecast_runs.user_id", "forecast_runs.id"],
            name="fk_goal_plan_runs_owner_forecast",
        ),
    )

    outcomes: Mapped[list[GoalPlanOutcome]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GoalPlanOutcome.rank",
    )
    periods: Mapped[list[GoalPlanPeriod]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GoalPlanPeriod.period_start",
    )
    events: Mapped[list[GoalPlanEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="(GoalPlanEvent.user_id, GoalPlanEvent.plan_run_id)",
        order_by=(
            "GoalPlanEvent.occurred_at, GoalPlanEvent.created_at, "
            "GoalPlanEvent.id"
        ),
    )

    @property
    def status(self) -> GoalPlanStatus:
        """Return the latest append-only lifecycle state."""
        if not self.events:
            return GoalPlanStatus.GENERATED
        return GoalPlanStatus(self.events[-1].status)

    @property
    def decided_at(self) -> datetime | None:
        """Return the latest lifecycle decision timestamp."""
        return self.events[-1].occurred_at if len(self.events) > 1 else None

    @property
    def successor_plan_id(self) -> UUID | None:
        """Return the successor recorded by a supersession event, if any."""
        for event in reversed(self.events):
            if event.status == GoalPlanStatus.SUPERSEDED:
                return event.successor_plan_id
        return None


class GoalPlanOutcome(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Freeze one goal and its evaluated result inside a generated plan."""

    __tablename__ = "goal_plan_outcomes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "plan_run_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_outcomes_owner_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "user_id", "plan_run_id", "id", name="uq_goal_plan_outcomes_owner_run_id"
        ),
        UniqueConstraint(
            "user_id",
            "plan_run_id",
            "id",
            "goal_id",
            name="uq_goal_plan_outcomes_owner_run_id_goal",
        ),
        UniqueConstraint(
            "plan_run_id", "goal_id", name="uq_goal_plan_outcomes_run_goal"
        ),
        CheckConstraint("length(trim(goal_name)) > 0", name="goal_name_not_blank"),
        CheckConstraint("rank > 0", name="rank_positive"),
        CheckConstraint(
            "goal_type IN ('travel', 'marriage', 'education', "
            "'emergency_fund', 'major_purchase', 'other')",
            name="goal_type_allowed",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="priority_allowed",
        ),
        CheckConstraint(
            "feasibility_state IN ('funded', 'secure', 'feasible', "
            "'stretch', 'unlikely', 'indeterminate', 'overdue', "
            "'unavailable')",
            name="feasibility_state_allowed",
        ),
        CheckConstraint(
            "deadline_risk IN ('funded', 'low', 'moderate', 'high', "
            "'critical', 'overdue', 'unknown')",
            name="deadline_risk_allowed",
        ),
        CheckConstraint(
            "evidence_reliability IN ('normal', 'provisional', "
            "'limited_horizon', 'unavailable')",
            name="evidence_reliability_allowed",
        ),
        CheckConstraint(
            "target_amount > 0 AND current_amount >= 0 AND "
            "starting_remaining_amount >= 0 AND allocated_amount >= 0 AND "
            "projected_remaining_amount >= 0 AND protected_shortfall >= 0 AND "
            "expected_shortfall >= 0 AND "
            "allocated_amount <= starting_remaining_amount",
            name="amounts_valid",
        ),
        CheckConstraint(
            "completion_probability IS NULL OR "
            "(completion_probability >= 0 AND completion_probability <= 1)",
            name="probability_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(feasibility_reason_codes) = 'array' AND "
            "jsonb_typeof(ranking_reason_codes) = 'array'",
            name="reason_arrays",
        ),
        Index(
            "ix_goal_plan_outcomes_user_run_rank",
            "user_id",
            "plan_run_id",
            "rank",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_run_id: Mapped[UUID] = mapped_column(nullable=False)
    goal_id: Mapped[UUID] = mapped_column(nullable=False)
    goal_name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal_type: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    target_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    current_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    starting_remaining_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    allocated_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    projected_remaining_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    protected_shortfall: Mapped[MoneyAmount] = mapped_column(nullable=False)
    expected_shortfall: Mapped[MoneyAmount] = mapped_column(nullable=False)
    expected_completion_period: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    projected_completion_period: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    deadline_met: Mapped[bool] = mapped_column(Boolean, nullable=False)
    feasibility_state: Mapped[str] = mapped_column(String(24), nullable=False)
    deadline_risk: Mapped[str] = mapped_column(String(24), nullable=False)
    completion_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6, asdecimal=True), nullable=True
    )
    evidence_reliability: Mapped[str] = mapped_column(String(24), nullable=False)
    feasibility_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    ranking_reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    run: Mapped[GoalPlanRun] = relationship(back_populates="outcomes")


class GoalPlanPeriod(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist one exact protected-capacity month in the selected schedule."""

    __tablename__ = "goal_plan_periods"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "plan_run_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_periods_owner_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "user_id", "plan_run_id", "id", name="uq_goal_plan_periods_owner_run_id"
        ),
        UniqueConstraint(
            "plan_run_id", "period_start", name="uq_goal_plan_periods_run_period"
        ),
        CheckConstraint(
            "available_capacity >= 0 AND allocated_amount >= 0 AND "
            "unallocated_amount >= 0 AND "
            "allocated_amount + unallocated_amount = available_capacity",
            name="totals_valid",
        ),
        Index(
            "ix_goal_plan_periods_user_run_period",
            "user_id",
            "plan_run_id",
            "period_start",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_run_id: Mapped[UUID] = mapped_column(nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    available_capacity: Mapped[MoneyAmount] = mapped_column(nullable=False)
    allocated_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    unallocated_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)

    run: Mapped[GoalPlanRun] = relationship(back_populates="periods")
    allocations: Mapped[list[GoalPlanAllocation]] = relationship(
        back_populates="period",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GoalPlanAllocation.rank",
    )


class GoalPlanAllocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persist one positive goal assignment within a schedule month."""

    __tablename__ = "goal_plan_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "plan_run_id", "period_id"],
            [
                "goal_plan_periods.user_id",
                "goal_plan_periods.plan_run_id",
                "goal_plan_periods.id",
            ],
            name="fk_goal_plan_allocations_owner_period",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
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
        UniqueConstraint(
            "plan_run_id",
            "period_id",
            "outcome_id",
            name="uq_goal_plan_allocations_period_outcome",
        ),
        CheckConstraint(
            "rank > 0 AND amount > 0 AND cumulative_amount > 0 AND "
            "projected_remaining_amount >= 0",
            name="values_valid",
        ),
        Index(
            "ix_goal_plan_allocations_user_run_period",
            "user_id",
            "plan_run_id",
            "period_id",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_run_id: Mapped[UUID] = mapped_column(nullable=False)
    period_id: Mapped[UUID] = mapped_column(nullable=False)
    outcome_id: Mapped[UUID] = mapped_column(nullable=False)
    goal_id: Mapped[UUID] = mapped_column(nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    cumulative_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)
    projected_remaining_amount: Mapped[MoneyAmount] = mapped_column(nullable=False)

    period: Mapped[GoalPlanPeriod] = relationship(back_populates="allocations")


class GoalPlanEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append one auditable generated, approval, rejection, or supersession event."""

    __tablename__ = "goal_plan_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "plan_run_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_events_owner_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "successor_plan_id"],
            ["goal_plan_runs.user_id", "goal_plan_runs.id"],
            name="fk_goal_plan_events_owner_successor",
        ),
        CheckConstraint(
            "status IN ('generated', 'approved', 'rejected', 'superseded')",
            name="status_allowed",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('generated', 'approved', 'rejected', 'superseded')",
            name="previous_status_allowed",
        ),
        CheckConstraint(
            "source IN ('system', 'user')",
            name="source_allowed",
        ),
        CheckConstraint(
            "(status = 'generated' AND previous_status IS NULL AND "
            "source = 'system' AND successor_plan_id IS NULL) OR "
            "(status IN ('approved', 'rejected') AND "
            "previous_status = 'generated' AND source = 'user' AND "
            "successor_plan_id IS NULL) OR "
            "(status = 'superseded' AND previous_status IN "
            "('generated', 'approved') AND source = 'system' AND "
            "successor_plan_id IS NOT NULL)",
            name="transition_shape_valid",
        ),
        CheckConstraint(
            "reason_code IS NULL OR length(trim(reason_code)) > 0",
            name="reason_not_blank",
        ),
        CheckConstraint(
            "successor_plan_id IS NULL OR successor_plan_id <> plan_run_id",
            name="successor_distinct",
        ),
        Index(
            "ix_goal_plan_events_user_run_occurred",
            "user_id",
            "plan_run_id",
            "occurred_at",
        ),
        Index(
            "uq_goal_plan_events_generated_once",
            "plan_run_id",
            unique=True,
            postgresql_where=text("status = 'generated'"),
        ),
        Index(
            "uq_goal_plan_events_decision_once",
            "plan_run_id",
            unique=True,
            postgresql_where=text("status IN ('approved', 'rejected')"),
        ),
        Index(
            "uq_goal_plan_events_superseded_once",
            "plan_run_id",
            unique=True,
            postgresql_where=text("status = 'superseded'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    plan_run_id: Mapped[UUID] = mapped_column(nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[GoalPlanEventSource] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
    successor_plan_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    run: Mapped[GoalPlanRun] = relationship(
        back_populates="events",
        foreign_keys=(user_id, plan_run_id),
    )
