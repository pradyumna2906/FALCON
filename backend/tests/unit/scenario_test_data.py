"""Deterministic Phase 11 evidence shared across scenario unit tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

from falcon_api.forecasting.persistence import ForecastPersistenceRepository
from falcon_api.goal_planning.persistence import GoalPlanRepository
from falcon_api.models.forecasting import ForecastPoint, ForecastRun
from falcon_api.scenario_simulation import (
    ScenarioAssumptions,
    ScenarioEvidenceService,
    ScenarioForecastRepository,
)
from goal_plan_test_data import (
    FORECAST_ID,
    NOW,
    OWNER_ID,
    transient_goal_plan_run,
)


SNAPSHOT_NOW = datetime(2026, 9, 15, 13, tzinfo=UTC)


class FixedScenarioClock:
    def now(self) -> datetime:
        return SNAPSHOT_NOW


def transient_savings_forecast() -> ForecastRun:
    """Return the exact forecast referenced by the standard Phase 10 fixture."""
    run = ForecastRun(
        id=FORECAST_ID,
        user_id=OWNER_ID,
        target="savings_amount",
        granularity="month",
        currency="INR",
        history_start=date(2026, 1, 1),
        history_end=date(2026, 8, 31),
        data_cutoff_at=NOW,
        source_last_updated_at=NOW,
        forecast_start=date(2026, 10, 1),
        forecast_end=date(2026, 11, 1),
        horizon=2,
        contract_version="2026.1",
        quality_policy_version="2026.1",
        evaluation_policy_version="2026.1",
        feature_policy_version="2026.1",
        selection_policy_version="2026.1",
        uncertainty_policy_version="2026.1",
        model_code="seasonal_naive",
        model_version="builtin-2026.1",
        model_parameters={},
        candidate_evidence={"calibration_residual_count": 12},
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
        points=[
            _point(1, date(2026, 10, 1)),
            _point(2, date(2026, 11, 1)),
        ],
        created_at=NOW,
        updated_at=NOW,
    )
    return run


def transient_supplemental_forecast(
    target: str,
    *,
    reliability: str = "normal",
) -> ForecastRun:
    """Return one cutoff-safe income or expense forecast over the plan horizon."""
    run = transient_savings_forecast()
    run.id = uuid4()
    run.target = target
    run.uncertainty_reliability = reliability
    for point in run.points:
        point.forecast_run_id = run.id
    return run


def transient_scenario_snapshot(
    scenarios: tuple[ScenarioAssumptions, ...],
    *,
    include_supplemental: bool = True,
):
    """Build one immutable Phase 11 snapshot through the production service."""
    run = transient_goal_plan_run()
    plans = AsyncMock(spec=GoalPlanRepository)
    plans.get.return_value = run
    forecasts = AsyncMock(spec=ForecastPersistenceRepository)
    forecasts.get.return_value = transient_savings_forecast()
    supplemental = AsyncMock(spec=ScenarioForecastRepository)

    async def latest_eligible(*args, target, **kwargs):
        del args, kwargs
        if not include_supplemental:
            return None
        return transient_supplemental_forecast(target.value)

    supplemental.latest_eligible.side_effect = latest_eligible
    service = ScenarioEvidenceService(
        plan_repository=plans,
        forecast_repository=forecasts,
        scenario_forecast_repository=supplemental,
        clock=FixedScenarioClock(),
    )
    return asyncio.run(
        service.build(
            AsyncMock(),
            user_id=OWNER_ID,
            source_plan_id=run.id,
            scenarios=scenarios,
        )
    )


def _point(step: int, period: date) -> ForecastPoint:
    return ForecastPoint(
        user_id=OWNER_ID,
        forecast_run_id=FORECAST_ID,
        step=step,
        period_start=period,
        expected_value=Decimal("75.0000"),
        lower_80=Decimal("60.0000"),
        upper_80=Decimal("90.0000"),
        lower_95=Decimal("50.0000"),
        upper_95=Decimal("100.0000"),
        created_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
        updated_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
