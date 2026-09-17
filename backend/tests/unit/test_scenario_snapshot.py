"""Tests for cutoff-safe owner-scoped Phase 11 scenario evidence."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import ANY, AsyncMock
from uuid import UUID, uuid4

import pytest

from falcon_api.core.errors import ApplicationError
from falcon_api.forecasting.persistence import ForecastPersistenceRepository
from falcon_api.goal_planning.persistence import GoalPlanRepository
from falcon_api.models.enums import GoalPlanEventSource, GoalPlanStatus
from falcon_api.models.goal_plan import GoalPlanEvent
from falcon_api.scenario_simulation import (
    GoalScenarioAdjustment,
    OneTimeExpenseAssumption,
    SCENARIO_SIMULATION_CONTRACT_VERSION,
    ScenarioAssumptions,
    ScenarioEvidenceService,
    ScenarioForecastRepository,
    ScenarioSnapshotWarning,
)
from goal_plan_test_data import GOAL_ID, NOW, OWNER_ID, transient_goal_plan_run
from scenario_test_data import (
    transient_savings_forecast,
    transient_supplemental_forecast,
)


SOURCE_PLAN_ID = UUID("40000000-0000-4000-8000-000000000001")
SNAPSHOT_NOW = datetime(2026, 9, 15, 13, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return SNAPSHOT_NOW


def _scenario(**changes) -> ScenarioAssumptions:
    values = {
        "name": "Unexpected expense",
        "one_time_expenses": (
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal("25"),
            ),
        ),
    }
    return ScenarioAssumptions(**{**values, **changes})


def _service(run=None, forecast=None, supplemental_forecasts=()):
    run = transient_goal_plan_run() if run is None else run
    run.id = SOURCE_PLAN_ID
    plans = AsyncMock(spec=GoalPlanRepository)
    plans.get.return_value = run
    forecasts = AsyncMock(spec=ForecastPersistenceRepository)
    forecasts.get.return_value = (
        transient_savings_forecast() if forecast is None else forecast
    )
    scenario_forecasts = AsyncMock(spec=ScenarioForecastRepository)
    if supplemental_forecasts:
        scenario_forecasts.latest_eligible.side_effect = supplemental_forecasts
    else:
        scenario_forecasts.latest_eligible.return_value = None
    return ScenarioEvidenceService(
        plan_repository=plans,
        forecast_repository=forecasts,
        scenario_forecast_repository=scenario_forecasts,
        clock=FixedClock(),
    ), plans, forecasts, run


def test_snapshot_freezes_owned_plan_forecast_and_user_hypotheses() -> None:
    service, plans, forecasts, run = _service()

    first = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=OWNER_ID,
            source_plan_id=run.id,
            scenarios=(_scenario(),),
        )
    )
    second = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=OWNER_ID,
            source_plan_id=run.id,
            scenarios=(_scenario(),),
        )
    )

    assert first == second
    assert first.snapshot_id == second.snapshot_id
    assert len(first.snapshot_id) == 64
    assert first.contract_version == SCENARIO_SIMULATION_CONTRACT_VERSION
    assert first.source_plan.run_id == SOURCE_PLAN_ID
    assert first.source_plan.planning_snapshot_id == "c" * 64
    assert first.forecast is not None
    assert first.forecast.run_id == run.forecast_run_id
    assert [item.period_start for item in first.forecast.points] == [
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]
    assert first.periods[0].available_capacity == Decimal("50.0000")
    assert first.goals[0].goal_id == GOAL_ID
    assert first.scenarios[0].one_time_expenses[0].amount == Decimal("25.0000")
    assert ScenarioSnapshotWarning.SOURCE_PLAN_GENERATED_ONLY in first.warnings
    plans.get.assert_awaited_with(
        ANY,
        user_id=OWNER_ID,
        plan_id=SOURCE_PLAN_ID,
    )
    forecasts.get.assert_awaited_with(
        ANY,
        user_id=OWNER_ID,
        run_id=run.forecast_run_id,
    )


def test_snapshot_hides_foreign_and_unavailable_source_plans() -> None:
    service, plans, _, run = _service()
    plans.get.return_value = None
    with pytest.raises(ApplicationError) as missing:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=uuid4(),
                source_plan_id=run.id,
                scenarios=(_scenario(),),
            )
        )
    assert missing.value.code == "scenario_source_plan_not_found"
    assert missing.value.status_code == 404

    run.events[-1].status = GoalPlanStatus.REJECTED.value
    plans.get.return_value = run
    with pytest.raises(ApplicationError) as unavailable:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=OWNER_ID,
                source_plan_id=run.id,
                scenarios=(_scenario(),),
            )
        )
    assert unavailable.value.code == "scenario_source_plan_unavailable"
    assert unavailable.value.status_code == 409


def test_snapshot_translates_invalid_internal_assumptions() -> None:
    service, _, _, run = _service()
    with pytest.raises(ApplicationError) as invalid:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=OWNER_ID,
                source_plan_id=run.id,
                scenarios=(),
            )
        )
    assert invalid.value.code == "scenario_invalid_assumptions"
    assert invalid.value.status_code == 422


@pytest.mark.parametrize(
    "mutate",
    [
        lambda run, forecast: setattr(forecast, "currency", "USD"),
        lambda run, forecast: setattr(forecast.points[0], "lower_95", Decimal("49")),
        lambda run, forecast: setattr(forecast, "data_cutoff_at", NOW + timedelta(days=1)),
        lambda run, forecast: setattr(forecast, "created_at", NOW + timedelta(days=1)),
        lambda run, forecast: setattr(forecast, "horizon", 3),
        lambda run, forecast: setattr(forecast, "forecast_start", date(2026, 9, 1)),
        lambda run, forecast: setattr(forecast.points[0], "lower_80", Decimal("80")),
        lambda run, forecast: setattr(run, "goal_count", 2),
        lambda run, forecast: setattr(run, "planning_cutoff_at", NOW + timedelta(days=1)),
    ],
)
def test_snapshot_rejects_mismatched_or_future_evidence(mutate) -> None:
    forecast = transient_savings_forecast()
    service, _, _, run = _service(forecast=forecast)
    mutate(run, forecast)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=OWNER_ID,
                source_plan_id=run.id,
                scenarios=(_scenario(),),
            )
        )
    assert error.value.code == "scenario_evidence_unavailable"
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "mutate",
    [
        lambda run, forecast: setattr(forecast, "user_id", uuid4()),
        lambda run, forecast: setattr(forecast, "target", "gross_income"),
        lambda run, forecast: setattr(forecast, "granularity", "day"),
        lambda run, forecast: setattr(
            forecast,
            "source_last_updated_at",
            NOW + timedelta(days=1),
        ),
        lambda run, forecast: forecast.points.pop(),
        lambda run, forecast: setattr(run, "user_id", uuid4()),
        lambda run, forecast: run.events.clear(),
        lambda run, forecast: setattr(run.events[0], "occurred_at", NOW.replace(tzinfo=None)),
        lambda run, forecast: setattr(run.outcomes[0], "rank", 2),
        lambda run, forecast: run.periods.reverse(),
    ],
)
def test_snapshot_rejects_corrupt_source_graphs(mutate) -> None:
    forecast = transient_savings_forecast()
    service, _, _, run = _service(forecast=forecast)
    mutate(run, forecast)
    with pytest.raises(ApplicationError) as error:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=OWNER_ID,
                source_plan_id=run.id,
                scenarios=(_scenario(),),
            )
        )
    assert error.value.code == "scenario_evidence_unavailable"


def test_snapshot_rejects_missing_referenced_forecast() -> None:
    service, _, forecasts, run = _service()
    forecasts.get.return_value = None
    with pytest.raises(ApplicationError) as error:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=OWNER_ID,
                source_plan_id=run.id,
                scenarios=(_scenario(),),
            )
        )
    assert error.value.code == "scenario_evidence_unavailable"


def test_snapshot_rejects_assumptions_outside_source_evidence() -> None:
    service, _, _, run = _service()
    cases = (
        _scenario(
            one_time_expenses=(
                OneTimeExpenseAssumption(
                    period_start=date(2026, 12, 1),
                    amount=Decimal("1"),
                ),
            )
        ),
        _scenario(
            one_time_expenses=(),
            goal_adjustments=(
                GoalScenarioAdjustment(
                    goal_id=uuid4(),
                    target_date=date(2027, 1, 1),
                ),
            ),
        ),
        _scenario(
            one_time_expenses=(),
            goal_adjustments=(
                GoalScenarioAdjustment(
                    goal_id=GOAL_ID,
                    target_date=date(2026, 9, 15),
                ),
            ),
        ),
    )
    for scenario in cases:
        with pytest.raises(ApplicationError) as error:
            asyncio.run(
                service.build(
                    AsyncMock(),
                    user_id=OWNER_ID,
                    source_plan_id=run.id,
                    scenarios=(scenario,),
                )
            )
        assert error.value.code == "scenario_evidence_unavailable"


def test_snapshot_rejects_goal_target_below_frozen_progress() -> None:
    service, _, _, run = _service()
    run.outcomes[0].current_amount = Decimal("50")
    scenario = _scenario(
        one_time_expenses=(),
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                target_amount=Decimal("25"),
            ),
        ),
    )
    with pytest.raises(ApplicationError) as error:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=OWNER_ID,
                source_plan_id=run.id,
                scenarios=(scenario,),
            )
        )
    assert error.value.code == "scenario_evidence_unavailable"


def test_snapshot_without_forecast_remains_explicitly_limited() -> None:
    run = transient_goal_plan_run(with_capacity=False)
    run.id = SOURCE_PLAN_ID
    service, _, forecasts, _ = _service(run=run)
    scenario = ScenarioAssumptions(
        name="Later deadline",
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                target_date=date(2027, 1, 31),
            ),
        ),
    )
    snapshot = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=OWNER_ID,
            source_plan_id=run.id,
            scenarios=(scenario,),
        )
    )

    assert snapshot.forecast is None
    assert ScenarioSnapshotWarning.FORECAST_UNAVAILABLE in snapshot.warnings
    forecasts.get.assert_not_awaited()


def test_approved_plan_and_provisional_forecast_have_precise_warnings() -> None:
    run = transient_goal_plan_run()
    run.id = SOURCE_PLAN_ID
    run.events.append(
        GoalPlanEvent(
            user_id=OWNER_ID,
            plan_run_id=run.id,
            previous_status=GoalPlanStatus.GENERATED.value,
            status=GoalPlanStatus.APPROVED.value,
            source=GoalPlanEventSource.USER,
            occurred_at=NOW + timedelta(minutes=30),
            successor_plan_id=None,
            reason_code="user_approved_plan",
            created_at=NOW + timedelta(minutes=30),
            updated_at=NOW + timedelta(minutes=30),
        )
    )
    forecast = transient_savings_forecast()
    forecast.uncertainty_reliability = "provisional"
    service, _, _, run = _service(run=run, forecast=forecast)

    snapshot = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=OWNER_ID,
            source_plan_id=run.id,
            scenarios=(_scenario(),),
        )
    )

    assert snapshot.source_plan.status is GoalPlanStatus.APPROVED
    assert snapshot.warnings == (ScenarioSnapshotWarning.FORECAST_PROVISIONAL,)


def test_percentage_scenarios_freeze_required_income_and_expense_forecasts() -> None:
    income = transient_supplemental_forecast(
        "gross_income",
        reliability="provisional",
    )
    expense = transient_supplemental_forecast("total_expense")
    service, _, _, run = _service(
        supplemental_forecasts=(income, expense),
    )
    scenario = ScenarioAssumptions(
        name="Income and expense pressure",
        income_change_percent=Decimal("-10"),
        expense_change_percent=Decimal("5"),
    )

    snapshot = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=OWNER_ID,
            source_plan_id=run.id,
            scenarios=(scenario,),
        )
    )

    assert snapshot.income_forecast is not None
    assert snapshot.income_forecast.run_id == income.id
    assert snapshot.expense_forecast is not None
    assert snapshot.expense_forecast.run_id == expense.id
    assert ScenarioSnapshotWarning.INCOME_FORECAST_PROVISIONAL in snapshot.warnings
    assert ScenarioSnapshotWarning.EXPENSE_FORECAST_UNAVAILABLE not in snapshot.warnings


def test_missing_required_supplemental_forecasts_are_explicit() -> None:
    service, _, _, run = _service()
    scenario = ScenarioAssumptions(
        name="Income and expense pressure",
        income_change_percent=Decimal("-10"),
        expense_change_percent=Decimal("5"),
    )

    snapshot = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=OWNER_ID,
            source_plan_id=run.id,
            scenarios=(scenario,),
        )
    )

    assert snapshot.income_forecast is None
    assert snapshot.expense_forecast is None
    assert ScenarioSnapshotWarning.INCOME_FORECAST_UNAVAILABLE in snapshot.warnings
    assert ScenarioSnapshotWarning.EXPENSE_FORECAST_UNAVAILABLE in snapshot.warnings


@pytest.mark.parametrize(
    "mutate",
    [
        lambda forecast: setattr(forecast, "user_id", uuid4()),
        lambda forecast: setattr(forecast, "target", "total_expense"),
        lambda forecast: setattr(forecast, "granularity", "day"),
        lambda forecast: setattr(forecast, "currency", "USD"),
        lambda forecast: setattr(
            forecast,
            "data_cutoff_at",
            NOW + timedelta(days=1),
        ),
        lambda forecast: setattr(
            forecast,
            "data_cutoff_at",
            NOW.replace(tzinfo=None),
        ),
        lambda forecast: setattr(
            forecast,
            "created_at",
            NOW + timedelta(days=1),
        ),
        lambda forecast: setattr(
            forecast,
            "source_last_updated_at",
            NOW + timedelta(days=1),
        ),
        lambda forecast: forecast.points.pop(),
        lambda forecast: setattr(forecast, "forecast_end", date(2026, 12, 1)),
        lambda forecast: setattr(
            forecast.points[0],
            "expected_value",
            Decimal("NaN"),
        ),
        lambda forecast: setattr(
            forecast.points[0],
            "lower_80",
            Decimal("80"),
        ),
    ],
)
def test_snapshot_rejects_corrupt_supplemental_forecasts(mutate) -> None:
    income = transient_supplemental_forecast("gross_income")
    mutate(income)
    service, _, _, run = _service(supplemental_forecasts=(income,))
    scenario = ScenarioAssumptions(
        name="Income pressure",
        income_change_percent=Decimal("-10"),
    )

    with pytest.raises(ApplicationError) as error:
        asyncio.run(
            service.build(
                AsyncMock(),
                user_id=OWNER_ID,
                source_plan_id=run.id,
                scenarios=(scenario,),
            )
        )

    assert error.value.code == "scenario_evidence_unavailable"
