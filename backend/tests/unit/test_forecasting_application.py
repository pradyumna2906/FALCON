"""Tests for end-to-end forecast orchestration and safe failures."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from falcon_api.core.errors import ApplicationError
from falcon_api.forecasting import (
    FinancialForecastService,
    ForecastGenerationCommand,
    ForecastGranularity,
    ForecastSourceBucket,
    ForecastTarget,
    HistoricalMeanBaseline,
    LastValueBaseline,
)
from falcon_api.forecasting.persistence import ForecastPersistenceRepository
from falcon_api.forecasting.repository import ForecastingRepository


def _command() -> ForecastGenerationCommand:
    return ForecastGenerationCommand(
        target=ForecastTarget.TOTAL_EXPENSE,
        granularity=ForecastGranularity.MONTH,
        currency="inr",
        history_start=date(2026, 1, 1),
        history_end=date(2026, 5, 31),
        horizon=2,
        trusted_timezone="Asia/Kolkata",
    )


def _buckets() -> tuple[ForecastSourceBucket, ...]:
    values = ("100", "110", "120", "130", "140")
    return tuple(
        ForecastSourceBucket(
            period_start=date(2026, month, 1),
            gross_income=Decimal("500"),
            total_expense=Decimal(value),
            transaction_count=2,
            source_last_updated_at=datetime(2026, month, 2, tzinfo=UTC),
        )
        for month, value in enumerate(values, start=1)
    )


def test_service_generates_calibrates_and_persists_under_trusted_owner() -> None:
    source = AsyncMock(spec=ForecastingRepository)
    source.list_source_buckets.return_value = _buckets()
    persistence = AsyncMock(spec=ForecastPersistenceRepository)
    persisted = Mock()
    persistence.create.return_value = persisted
    monitor = Mock()
    monitor.start.return_value = 1.0
    service = FinancialForecastService(
        source_repository=source,
        persistence_repository=persistence,
        candidate_factory=lambda _: (LastValueBaseline(), HistoricalMeanBaseline()),
        monitor=monitor,
        clock=lambda: datetime(2026, 6, 1, tzinfo=UTC),
    )
    session = AsyncMock()
    user_id = uuid4()

    result = asyncio.run(
        service.generate(session, user_id=user_id, command=_command())
    )

    assert result is persisted
    assert source.list_source_buckets.await_args.kwargs["user_id"] == user_id
    payload = persistence.create.await_args.kwargs["payload"]
    assert persistence.create.await_args.kwargs["user_id"] == user_id
    assert payload.currency == "INR"
    assert payload.forecast_start == date(2026, 6, 1)
    assert payload.forecast_end == date(2026, 7, 1)
    assert tuple(point.step for point in payload.points) == (1, 2)
    assert payload.model_code in {"last_value", "historical_mean"}
    assert payload.candidate_evidence["quality_eligibility"] == "normal"
    monitor.record_generation.assert_called_once()


def test_service_rejects_empty_or_too_short_history_without_persistence() -> None:
    source = AsyncMock(spec=ForecastingRepository)
    persistence = AsyncMock(spec=ForecastPersistenceRepository)
    service = FinancialForecastService(
        source_repository=source,
        persistence_repository=persistence,
        candidate_factory=lambda _: (LastValueBaseline(),),
        clock=lambda: datetime(2026, 6, 1, tzinfo=UTC),
    )
    source.list_source_buckets.return_value = ()
    with pytest.raises(ApplicationError) as unavailable:
        asyncio.run(service.generate(AsyncMock(), user_id=uuid4(), command=_command()))
    assert unavailable.value.code == "forecast_history_unavailable"

    source.list_source_buckets.return_value = _buckets()[:1]
    short = ForecastGenerationCommand(
        **{
            field: getattr(_command(), field)
            for field in _command().__dataclass_fields__
            if field not in {"history_start", "history_end"}
        },
        history_start=date(2026, 1, 1),
        history_end=date(2026, 1, 31),
    )
    with pytest.raises(ApplicationError) as insufficient:
        asyncio.run(service.generate(AsyncMock(), user_id=uuid4(), command=short))
    assert insufficient.value.code == "forecast_history_insufficient"
    persistence.create.assert_not_awaited()


def test_service_get_is_owner_scoped_and_returns_safe_not_found() -> None:
    persistence = AsyncMock(spec=ForecastPersistenceRepository)
    persistence.get.return_value = None
    service = FinancialForecastService(persistence_repository=persistence)
    user_id, run_id = uuid4(), uuid4()
    with pytest.raises(ApplicationError) as not_found:
        asyncio.run(service.get(AsyncMock(), user_id=user_id, run_id=run_id))
    assert not_found.value.code == "forecast_not_found"
    assert persistence.get.await_args.kwargs == {
        "user_id": user_id,
        "run_id": run_id,
    }
