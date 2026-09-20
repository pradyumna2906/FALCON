"""Real PostgreSQL lifecycle and isolation tests for persistent goal plans."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError

from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.forecasting import (
    ForecastGranularity,
    ForecastPersistenceRepository,
    ForecastPointWrite,
    ForecastRunWrite,
    ForecastTarget,
)
from falcon_api.goal_planning import (
    GoalCreateCommand,
    GoalPlanGenerationCommand,
    GoalService,
    LinearProgramSolution,
    LinearSolverStatus,
    MultiGoalOptimizationService,
)
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.enums import (
    GoalPlanStatus,
    GoalPriority,
    GoalType,
    UserStatus,
)
from falcon_api.models.goal_plan import (
    GoalPlanAllocation,
    GoalPlanEvent,
    GoalPlanOutcome,
    GoalPlanPeriod,
    GoalPlanRun,
)
from falcon_api.models.planning import GoalContribution
from falcon_api.models.scenario import (
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioEvent,
    ScenarioGoalOutcome,
    ScenarioPeriod,
    ScenarioSimulationRun,
)
from falcon_api.models.user import User
from falcon_api.scenario_simulation import (
    MONTE_CARLO_PROBABILITY_METHOD,
    MonteCarloConfig,
    OneTimeExpenseAssumption,
    ScenarioAssumptions,
    ScenarioEvidenceService,
    ScenarioEvaluationStatus,
    ScenarioSimulationRepository,
    ScenarioSnapshotWarning,
    analyze_scenario_decisions,
    evaluate_deterministic_scenarios,
    evaluate_scenario_risk,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class FixedClock:
    def __init__(self, instant: datetime = _NOW) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class ZeroSolver:
    def solve(self, *, objective, upper_bound_matrix, upper_bounds, bounds):
        del upper_bound_matrix, upper_bounds, bounds
        return LinearProgramSolution(
            status=LinearSolverStatus.OPTIMAL,
            values=tuple(0.0 for _ in objective),
            objective_value=0.0,
            solver_name="integration_zero_solver",
            solver_version="1",
            message="valid but dominated",
            iterations=0,
        )


def integration_settings() -> Settings:
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def test_goal_plan_history_is_immutable_owner_scoped_and_cascades() -> None:
    asyncio.run(_exercise_goal_plan_history())


async def _exercise_goal_plan_history() -> None:
    resources = create_database_resources(integration_settings())
    owner_id = uuid4()
    other_id = uuid4()
    goals = GoalService(clock=FixedClock())
    forecasts = ForecastPersistenceRepository()
    simulations = ScenarioSimulationRepository()
    plan_ids: set[UUID] = set()
    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([_user(owner_id, "plan-owner"), _user(other_id, "other")])

        async with transaction_scope(resources.session_factory) as session:
            await goals.create(
                session,
                user_id=owner_id,
                default_currency="INR",
                trusted_timezone="Asia/Kolkata",
                command=GoalCreateCommand(
                    name="Education Fund",
                    goal_type=GoalType.EDUCATION,
                    target_amount=Decimal("100.0000"),
                    starting_amount=Decimal("0.0000"),
                    currency=None,
                    target_date=date(2026, 12, 31),
                    priority=GoalPriority.HIGH,
                    description=None,
                ),
            )
            forecast = await forecasts.create(
                session,
                user_id=owner_id,
                payload=_forecast_payload(),
            )
            forecast_id = forecast.id
            planning_now = max(
                _NOW,
                forecast.created_at,
                forecast.updated_at,
            ) + timedelta(seconds=1)

        plans = MultiGoalOptimizationService(
            solver=ZeroSolver(),
            clock=FixedClock(planning_now),
        )

        async with transaction_scope(resources.session_factory) as session:
            generated = await plans.generate(
                session,
                user_id=owner_id,
                command=GoalPlanGenerationCommand(
                    currency="INR",
                    trusted_timezone="Asia/Kolkata",
                ),
            )
            first_id = generated.id
            plan_ids.add(first_id)
            assert generated.forecast_run_id == forecast_id
            assert generated.status is GoalPlanStatus.GENERATED
            assert generated.goal_count == len(generated.outcomes) == 1
            assert len(generated.periods) == 2
            assert sum(len(item.allocations) for item in generated.periods) == 2
            assert generated.allocated_savings == Decimal("100.0000")

        async with transaction_scope(resources.session_factory) as session:
            owner_plan = await plans.get(
                session,
                user_id=owner_id,
                plan_id=first_id,
            )
            assert owner_plan.status is GoalPlanStatus.GENERATED
            assert len(owner_plan.events) == 1
            with pytest.raises(ApplicationError) as hidden:
                await plans.get(
                    session,
                    user_id=other_id,
                    plan_id=first_id,
                )
            assert hidden.value.code == "goal_plan_not_found"

        scenario_evidence = ScenarioEvidenceService(
            clock=FixedClock(planning_now + timedelta(seconds=1))
        )
        assumptions = ScenarioAssumptions(
            name="Unexpected expense",
            one_time_expenses=(
                OneTimeExpenseAssumption(
                    period_start=date(2026, 10, 1),
                    amount=Decimal("25.0000"),
                ),
            ),
        )
        async with transaction_scope(resources.session_factory) as session:
            snapshot = await scenario_evidence.build(
                session,
                user_id=owner_id,
                source_plan_id=first_id,
                scenarios=(assumptions,),
            )
            assert snapshot.user_id == owner_id
            assert snapshot.source_plan.run_id == first_id
            assert snapshot.forecast is not None
            assert snapshot.forecast.run_id == forecast_id
            assert snapshot.periods[0].available_capacity == Decimal("50.0000")
            assert snapshot.scenarios == (assumptions,)
            assert (
                ScenarioSnapshotWarning.SOURCE_PLAN_GENERATED_ONLY
                in snapshot.warnings
            )
            evaluations = evaluate_deterministic_scenarios(
                snapshot,
                solver=ZeroSolver(),
            )
            assert len(evaluations) == 4
            assert evaluations[0].allocated_total == Decimal("100.0000")
            assert evaluations[3].allocated_total == Decimal("75.0000")
            assert (
                evaluations[3].status
                is ScenarioEvaluationStatus.GUARDED_FALLBACK
            )
            risk = evaluate_scenario_risk(
                snapshot,
                config=MonteCarloConfig(trial_count=128, seed=11),
                solver=ZeroSolver(),
            )
            assert len(risk) == 4
            assert risk[3].trial_count == 128
            assert risk[3].probability_method == MONTE_CARLO_PROBABILITY_METHOD
            assert risk[3].goals[0].completion_denominator == 128
            analysis = analyze_scenario_decisions(
                snapshot,
                config=MonteCarloConfig(trial_count=128, seed=11),
                solver=ZeroSolver(),
            )
            persisted = await simulations.create(
                session,
                user_id=owner_id,
                snapshot=snapshot,
                analysis=analysis,
                occurred_at=planning_now + timedelta(seconds=2),
            )
            simulation_id = persisted.id
            assert persisted.root_seed == 11
            assert persisted.snapshot_id == snapshot.snapshot_id
            assert persisted.analysis_id == analysis.analysis_id
            assert len(persisted.definitions) == 4
            assert len(persisted.comparisons) == 4
            with pytest.raises(ApplicationError) as hidden_snapshot:
                await scenario_evidence.build(
                    session,
                    user_id=other_id,
                    source_plan_id=first_id,
                    scenarios=(assumptions,),
                )
            assert hidden_snapshot.value.code == "scenario_source_plan_not_found"

        async with transaction_scope(resources.session_factory) as session:
            owner_run = await simulations.get(
                session,
                user_id=owner_id,
                run_id=simulation_id,
                for_update=True,
            )
            assert owner_run is not None
            assert owner_run.selected_scenario_id is None
            assert len(owner_run.events) == 1
            assert (
                await simulations.get(
                    session,
                    user_id=other_id,
                    run_id=simulation_id,
                )
                is None
            )
            selected_id = owner_run.definitions[0].id
            await simulations.select(
                session,
                run=owner_run,
                user_id=owner_id,
                scenario_definition_id=selected_id,
                occurred_at=planning_now + timedelta(seconds=3),
            )
            assert owner_run.selected_scenario_id == selected_id
            await simulations.clear_selection(
                session,
                run=owner_run,
                user_id=owner_id,
                expected_scenario_definition_id=selected_id,
                occurred_at=planning_now + timedelta(seconds=4),
            )
            assert owner_run.selected_scenario_id is None
            assert len(owner_run.events) == 3

        with pytest.raises(DBAPIError):
            async with transaction_scope(resources.session_factory) as session:
                await session.execute(
                    delete(GoalPlanRun).where(GoalPlanRun.id == first_id)
                )

        with pytest.raises(DBAPIError):
            async with transaction_scope(resources.session_factory) as session:
                await session.execute(
                    text(
                        "UPDATE scenario_simulation_runs SET trial_count = 64 "
                        "WHERE id = :simulation_id"
                    ),
                    {"simulation_id": simulation_id},
                )

        async with transaction_scope(resources.session_factory) as session:
            approved = await plans.approve(
                session,
                user_id=owner_id,
                plan_id=first_id,
            )
            assert approved.status is GoalPlanStatus.APPROVED
            assert len(approved.events) == 2
            assert approved.events[-1].reason_code == "user_approved_plan"
            contribution_count = await session.scalar(
                select(func.count())
                .select_from(GoalContribution)
                .where(GoalContribution.user_id == owner_id)
            )
            assert contribution_count == 0

        async with transaction_scope(resources.session_factory) as session:
            successor = await plans.regenerate(
                session,
                user_id=owner_id,
                plan_id=first_id,
                trusted_timezone="Asia/Kolkata",
            )
            successor_id = successor.id
            plan_ids.add(successor_id)
            assert successor.predecessor_plan_id == first_id
            assert successor.status is GoalPlanStatus.GENERATED

        async with transaction_scope(resources.session_factory) as session:
            previous = await plans.get(
                session,
                user_id=owner_id,
                plan_id=first_id,
            )
            assert previous.status is GoalPlanStatus.SUPERSEDED
            assert previous.successor_plan_id == successor_id
            assert [event.status for event in previous.events] == [
                "generated",
                "approved",
                "superseded",
            ]
            recent = await plans.list_recent(session, user_id=owner_id, limit=10)
            assert {item.id for item in recent} == plan_ids
            assert await plans.list_recent(session, user_id=other_id, limit=10) == ()

        with pytest.raises(DBAPIError):
            async with transaction_scope(resources.session_factory) as session:
                await session.execute(
                    text(
                        "UPDATE goal_plan_runs SET strategy = 'blocked' "
                        "WHERE id = :plan_id"
                    ),
                    {"plan_id": successor_id},
                )

        async with transaction_scope(resources.session_factory) as session:
            unchanged = await plans.get(
                session,
                user_id=owner_id,
                plan_id=successor_id,
            )
            assert unchanged.strategy == "guarded_greedy_fallback"

        async with transaction_scope(resources.session_factory) as session:
            await session.execute(delete(User).where(User.id == owner_id))
            for model in (
                GoalPlanRun,
                GoalPlanOutcome,
                GoalPlanPeriod,
                GoalPlanAllocation,
                GoalPlanEvent,
                ScenarioSimulationRun,
                ScenarioDefinition,
                ScenarioPeriod,
                ScenarioGoalOutcome,
                ScenarioComparison,
                ScenarioEvent,
            ):
                remaining = await session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.user_id == owner_id)
                )
                assert remaining == 0
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(
                delete(User).where(User.id.in_((owner_id, other_id)))
            )
        await resources.dispose()


def _forecast_payload() -> ForecastRunWrite:
    points = tuple(
        ForecastPointWrite(
            step=step,
            period_start=period,
            expected_value=Decimal("75.0000"),
            lower_80=Decimal("60.0000"),
            upper_80=Decimal("90.0000"),
            lower_95=Decimal("50.0000"),
            upper_95=Decimal("100.0000"),
        )
        for step, period in enumerate(
            (date(2026, 10, 1), date(2026, 11, 1)),
            start=1,
        )
    )
    return ForecastRunWrite(
        target=ForecastTarget.SAVINGS_AMOUNT,
        granularity=ForecastGranularity.MONTH,
        currency="INR",
        history_start=date(2026, 1, 1),
        history_end=date(2026, 9, 14),
        data_cutoff_at=_NOW,
        source_last_updated_at=_NOW,
        forecast_start=date(2026, 10, 1),
        forecast_end=date(2026, 11, 1),
        contract_version="2026.1",
        quality_policy_version="2026.1",
        evaluation_policy_version="2026.1",
        feature_policy_version="2026.1",
        selection_policy_version="2026.1",
        uncertainty_policy_version="2026.1",
        model_code="integration_fixture",
        model_version="1",
        model_parameters={},
        candidate_evidence={"evaluated": ["integration_fixture"]},
        selection_metric="wape",
        validation_mae=Decimal("1"),
        validation_rmse=Decimal("1"),
        validation_wape=Decimal("0.1"),
        validation_bias=Decimal("0"),
        test_mae=Decimal("1"),
        test_rmse=Decimal("1"),
        test_wape=Decimal("0.1"),
        test_bias=Decimal("0"),
        uncertainty_method="absolute_residual_conformal",
        uncertainty_reliability="normal",
        points=points,
    )


def _user(user_id: UUID, label: str) -> User:
    return User(
        id=user_id,
        email=f"{label}-{uuid4().hex}@falcon.test",
        status=UserStatus.ACTIVE,
        display_name=label,
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
