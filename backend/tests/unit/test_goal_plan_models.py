"""Database-model integrity contracts for immutable goal-plan history."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index
from sqlalchemy.orm import configure_mappers

from falcon_api.infrastructure.persistence import Base
from falcon_api.models import register_models
from falcon_api.models.goal_plan import (
    GoalPlanAllocation,
    GoalPlanEvent,
    GoalPlanOutcome,
    GoalPlanPeriod,
    GoalPlanRun,
)
from goal_plan_test_data import NOW, transient_goal_plan_run


_PLAN_TABLES = {
    "goal_plan_runs",
    "goal_plan_outcomes",
    "goal_plan_periods",
    "goal_plan_allocations",
    "goal_plan_events",
}


def _check_names(table_name: str) -> set[str]:
    return {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    }


def _foreign_keys(table_name: str) -> dict[str, ForeignKeyConstraint]:
    return {
        constraint.name: constraint
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _indexes(table_name: str) -> dict[str, Index]:
    return {
        index.name: index
        for index in Base.metadata.tables[table_name].indexes
        if index.name is not None
    }


def test_goal_plan_models_register_five_tables_and_configure_relationships() -> None:
    register_models()
    configure_mappers()

    assert _PLAN_TABLES <= set(Base.metadata.tables)
    assert GoalPlanRun.__table__.name == "goal_plan_runs"
    assert GoalPlanOutcome.__table__.name == "goal_plan_outcomes"
    assert GoalPlanPeriod.__table__.name == "goal_plan_periods"
    assert GoalPlanAllocation.__table__.name == "goal_plan_allocations"
    assert GoalPlanEvent.__table__.name == "goal_plan_events"


def test_plan_records_use_uuid_and_timezone_aware_audit_columns() -> None:
    for table_name in _PLAN_TABLES:
        table = Base.metadata.tables[table_name]
        assert table.c.id.primary_key is True
        assert table.c.id.default is not None
        assert table.c.created_at.type.timezone is True
        assert table.c.updated_at.type.timezone is True

    assert GoalPlanRun.__table__.c.planning_cutoff_at.type.timezone is True
    assert GoalPlanEvent.__table__.c.occurred_at.type.timezone is True


def test_plan_owner_foreign_keys_prevent_cross_owner_graphs() -> None:
    run_keys = _foreign_keys("goal_plan_runs")
    assert run_keys["fk_goal_plan_runs_user_id_users"].ondelete == "CASCADE"
    assert run_keys["fk_goal_plan_runs_owner_forecast"].ondelete is None
    assert run_keys["fk_goal_plan_runs_owner_predecessor"].ondelete is None

    assert "fk_goal_plan_outcomes_owner_run" in _foreign_keys(
        "goal_plan_outcomes"
    )
    assert "fk_goal_plan_periods_owner_run" in _foreign_keys(
        "goal_plan_periods"
    )
    allocation_keys = _foreign_keys("goal_plan_allocations")
    assert set(
        allocation_keys["fk_goal_plan_allocations_owner_outcome"].column_keys
    ) == {"user_id", "plan_run_id", "outcome_id", "goal_id"}
    event_keys = _foreign_keys("goal_plan_events")
    assert event_keys["fk_goal_plan_events_owner_successor"].ondelete is None


def test_plan_checks_freeze_exact_money_enums_and_event_shapes() -> None:
    assert {
        "ck_goal_plan_runs_hashes_sha256_hex",
        "ck_goal_plan_runs_money_totals_valid",
        "ck_goal_plan_runs_assessment_counts_reconcile",
        "ck_goal_plan_runs_strategy_allowed",
    } <= _check_names("goal_plan_runs")
    assert {
        "ck_goal_plan_outcomes_amounts_valid",
        "ck_goal_plan_outcomes_probability_valid",
        "ck_goal_plan_outcomes_goal_type_allowed",
        "ck_goal_plan_outcomes_priority_allowed",
        "ck_goal_plan_outcomes_feasibility_state_allowed",
        "ck_goal_plan_outcomes_deadline_risk_allowed",
        "ck_goal_plan_outcomes_evidence_reliability_allowed",
    } <= _check_names("goal_plan_outcomes")
    assert "ck_goal_plan_periods_totals_valid" in _check_names(
        "goal_plan_periods"
    )
    assert "ck_goal_plan_allocations_values_valid" in _check_names(
        "goal_plan_allocations"
    )
    assert {
        "ck_goal_plan_events_transition_shape_valid",
        "ck_goal_plan_events_successor_distinct",
    } <= _check_names("goal_plan_events")


def test_plan_history_indexes_support_owner_reads_and_single_transitions() -> None:
    assert {
        "ix_goal_plan_runs_user_created",
        "ix_goal_plan_runs_user_currency_created",
    } <= set(_indexes("goal_plan_runs"))
    event_indexes = _indexes("goal_plan_events")
    for name, status in (
        ("uq_goal_plan_events_generated_once", "generated"),
        ("uq_goal_plan_events_decision_once", "approved"),
        ("uq_goal_plan_events_superseded_once", "superseded"),
    ):
        index = event_indexes[name]
        assert index.unique is True
        predicate = str(index.dialect_options["postgresql"]["where"])
        assert status in predicate


def test_plan_status_is_derived_from_append_only_events_not_mutable_column() -> None:
    run = transient_goal_plan_run()

    assert "status" not in GoalPlanRun.__table__.c
    assert "decided_at" not in GoalPlanRun.__table__.c
    assert run.status.value == "generated"
    assert run.decided_at is None
    run.events[0].occurred_at = NOW
    run.events.clear()
    assert run.status.value == "generated"


def test_plan_tables_do_not_copy_raw_financial_or_transaction_evidence() -> None:
    forbidden = {
        "account_id",
        "account_name",
        "transaction_id",
        "transaction_description",
        "liquid_balance",
        "outstanding_debt",
        "monthly_debt_payment",
        "email",
    }
    columns = {
        column.name
        for table_name in _PLAN_TABLES
        for column in Base.metadata.tables[table_name].columns
    }
    assert forbidden.isdisjoint(columns)
