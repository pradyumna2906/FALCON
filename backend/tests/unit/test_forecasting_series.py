"""Tests for deterministic calendar-complete model-input series."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from falcon_api.forecasting import (
    ForecastGranularity,
    ForecastHistoryWindow,
    ForecastSourceBucket,
    ForecastTarget,
    build_forecast_series,
)


_CUTOFF = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _bucket(
    period_start: date,
    *,
    income: str = "0",
    expense: str = "0",
    count: int = 1,
    updated_at: datetime = _CUTOFF,
) -> ForecastSourceBucket:
    return ForecastSourceBucket(
        period_start=period_start,
        gross_income=Decimal(income),
        total_expense=Decimal(expense),
        transaction_count=count,
        source_last_updated_at=updated_at,
    )


def test_daily_series_fills_missing_dates_and_preserves_exact_money() -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 3),
        timezone="UTC",
        granularity=ForecastGranularity.DAY,
        data_cutoff_at=_CUTOFF,
    )
    result = build_forecast_series(
        target=ForecastTarget.NET_CASH_FLOW,
        currency="inr",
        window=window,
        buckets=(
            _bucket(date(2026, 9, 1), income="1000", expense="250", count=2),
            _bucket(date(2026, 9, 3), expense="125.5"),
        ),
    )

    assert result.currency == "INR"
    assert tuple(point.period_start for point in result.points) == (
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
    )
    assert tuple(point.value for point in result.points) == (
        Decimal("750.0000"),
        Decimal("0.0000"),
        Decimal("-125.5000"),
    )
    assert tuple(point.is_observed for point in result.points) == (True, False, True)
    assert result.observed_period_count == 2
    assert result.transaction_count == 3
    assert result.source_last_updated_at == _CUTOFF


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (ForecastTarget.GROSS_INCOME, Decimal("1000.0000")),
        (ForecastTarget.TOTAL_EXPENSE, Decimal("250.0000")),
        (ForecastTarget.NET_CASH_FLOW, Decimal("750.0000")),
        (ForecastTarget.SAVINGS_AMOUNT, Decimal("750.0000")),
    ],
)
def test_each_target_uses_its_frozen_metric_formula(
    target: ForecastTarget, expected: Decimal
) -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 1),
        timezone="UTC",
        granularity=ForecastGranularity.DAY,
        data_cutoff_at=_CUTOFF,
    )
    result = build_forecast_series(
        target=target,
        currency="INR",
        window=window,
        buckets=(_bucket(date(2026, 9, 1), income="1000", expense="250"),),
    )
    assert result.points[0].value == expected


def test_monthly_series_steps_by_calendar_month() -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 8, 31),
        timezone="UTC",
        granularity=ForecastGranularity.MONTH,
        data_cutoff_at=_CUTOFF,
    )
    result = build_forecast_series(
        target=ForecastTarget.TOTAL_EXPENSE,
        currency="USD",
        window=window,
        buckets=(_bucket(date(2026, 7, 1), expense="500"),),
    )
    assert tuple(point.period_start for point in result.points) == (
        date(2026, 6, 1),
        date(2026, 7, 1),
        date(2026, 8, 1),
    )
    assert tuple(point.value for point in result.points) == (
        Decimal("0.0000"),
        Decimal("500.0000"),
        Decimal("0.0000"),
    )


def test_series_rejects_duplicate_misaligned_and_future_known_buckets() -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 8, 31),
        timezone="UTC",
        granularity=ForecastGranularity.MONTH,
        data_cutoff_at=_CUTOFF,
    )
    valid = _bucket(date(2026, 7, 1))
    with pytest.raises(ValueError, match="unique"):
        build_forecast_series(
            target=ForecastTarget.GROSS_INCOME,
            currency="INR",
            window=window,
            buckets=(valid, valid),
        )
    with pytest.raises(ValueError, match="misaligned"):
        build_forecast_series(
            target=ForecastTarget.GROSS_INCOME,
            currency="INR",
            window=window,
            buckets=(_bucket(date(2026, 7, 2)),),
        )
    with pytest.raises(ValueError, match="newer"):
        build_forecast_series(
            target=ForecastTarget.GROSS_INCOME,
            currency="INR",
            window=window,
            buckets=(
                _bucket(
                    date(2026, 7, 1),
                    updated_at=_CUTOFF + timedelta(seconds=1),
                ),
            ),
        )


def test_source_buckets_reject_impossible_values() -> None:
    with pytest.raises(ValueError, match="positive row count"):
        _bucket(date(2026, 9, 1), count=0)
    with pytest.raises(ValueError, match="cannot be negative"):
        _bucket(date(2026, 9, 1), income="-1")
    with pytest.raises(ValueError, match="timezone-aware"):
        _bucket(
            date(2026, 9, 1),
            updated_at=datetime(2026, 9, 1),
        )
