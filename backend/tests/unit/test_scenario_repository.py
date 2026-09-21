"""Tests for owner- and cutoff-scoped Phase 11 forecast selection."""

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.forecasting.semantics import ForecastTarget
from falcon_api.scenario_simulation import ScenarioForecastRepository


PERIODS = (date(2026, 10, 1), date(2026, 11, 1))
CUTOFF = datetime(2026, 9, 15, 12, tzinfo=UTC)


def test_latest_eligible_forecast_query_is_owner_cutoff_and_horizon_scoped() -> None:
    repository = ScenarioForecastRepository()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    owner_id = uuid4()

    result = asyncio.run(
        repository.latest_eligible(
            session,
            user_id=owner_id,
            currency="INR",
            target=ForecastTarget.GROSS_INCOME,
            cutoff_at=CUTOFF,
            periods=PERIODS,
        )
    )

    assert result is None
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "forecast_runs.user_id =" in sql
    assert "forecast_runs.currency =" in sql
    assert "forecast_runs.target =" in sql
    assert "forecast_runs.granularity =" in sql
    assert "forecast_runs.data_cutoff_at <=" in sql
    assert "forecast_runs.created_at <=" in sql
    assert "forecast_runs.source_last_updated_at IS NULL" in sql
    assert "forecast_runs.forecast_start =" in sql
    assert "forecast_runs.forecast_end =" in sql
    assert "forecast_runs.horizon =" in sql
    assert owner_id in compiled.params.values()
    assert "gross_income" in compiled.params.values()
    assert "month" in compiled.params.values()


def test_supplemental_repository_rejects_unsafe_selection_inputs() -> None:
    repository = ScenarioForecastRepository()
    session = AsyncMock(spec=AsyncSession)
    common = {
        "session": session,
        "user_id": uuid4(),
        "currency": "INR",
        "cutoff_at": CUTOFF,
        "periods": PERIODS,
    }
    with pytest.raises(ValueError, match="target is invalid"):
        asyncio.run(
            repository.latest_eligible(
                **common,
                target=ForecastTarget.SAVINGS_AMOUNT,
            )
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(
            repository.latest_eligible(
                **{**common, "cutoff_at": CUTOFF.replace(tzinfo=None)},
                target=ForecastTarget.TOTAL_EXPENSE,
            )
        )
    with pytest.raises(ValueError, match="ordered month boundaries"):
        asyncio.run(
            repository.latest_eligible(
                **{**common, "periods": (date(2026, 10, 2),)},
                target=ForecastTarget.TOTAL_EXPENSE,
            )
        )
    assert (
        asyncio.run(
            repository.latest_eligible(
                **{**common, "periods": ()},
                target=ForecastTarget.TOTAL_EXPENSE,
            )
        )
        is None
    )
