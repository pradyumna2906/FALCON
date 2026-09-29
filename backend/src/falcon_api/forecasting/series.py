"""Build calendar-complete, exact-decimal forecasting input series."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from collections.abc import Iterator

from falcon_api.analytics.types import money
from falcon_api.forecasting.periods import ForecastHistoryWindow
from falcon_api.forecasting.semantics import (
    ForecastGranularity,
    ForecastTarget,
    normalize_forecast_currency,
)
from falcon_api.forecasting.types import (
    ForecastSeries,
    ForecastSeriesPoint,
    ForecastSourceBucket,
)


_ZERO = Decimal("0.0000")


def build_forecast_series(
    *,
    target: ForecastTarget,
    currency: str,
    window: ForecastHistoryWindow,
    buckets: tuple[ForecastSourceBucket, ...],
) -> ForecastSeries:
    """Fill absent buckets with explicit zero values inside a frozen window."""
    resolved_target = ForecastTarget(target)
    resolved_currency = normalize_forecast_currency(currency)
    expected_starts = tuple(_period_starts(window))
    by_start: dict[date, ForecastSourceBucket] = {}
    for bucket in buckets:
        if bucket.period_start not in expected_starts:
            raise ValueError("Source bucket falls outside or is misaligned to history.")
        if bucket.period_start in by_start:
            raise ValueError("Source buckets must be unique per calendar period.")
        if bucket.source_last_updated_at > window.data_cutoff_at:
            raise ValueError("Source bucket is newer than the dataset cutoff.")
        by_start[bucket.period_start] = bucket

    points = tuple(
        _series_point(
            target=resolved_target,
            period_start=period_start,
            source=by_start.get(period_start),
        )
        for period_start in expected_starts
    )
    source_last_updated_at = max(
        (bucket.source_last_updated_at for bucket in buckets),
        default=None,
    )
    return ForecastSeries(
        target=resolved_target,
        granularity=ForecastGranularity(window.granularity),
        currency=resolved_currency,
        history_start=window.date_from,
        history_end=window.date_to,
        data_cutoff_at=window.data_cutoff_at,
        points=points,
        source_last_updated_at=source_last_updated_at,
    )


def _series_point(
    *,
    target: ForecastTarget,
    period_start: date,
    source: ForecastSourceBucket | None,
) -> ForecastSeriesPoint:
    if source is None:
        return ForecastSeriesPoint(
            period_start=period_start,
            value=_ZERO,
            transaction_count=0,
            is_observed=False,
        )
    if target is ForecastTarget.GROSS_INCOME:
        value = source.gross_income
    elif target is ForecastTarget.TOTAL_EXPENSE:
        value = source.total_expense
    else:
        value = source.net_cash_flow
    return ForecastSeriesPoint(
        period_start=period_start,
        value=money(value),
        transaction_count=source.transaction_count,
        is_observed=True,
    )


def _period_starts(window: ForecastHistoryWindow) -> Iterator[date]:
    current = window.date_from
    granularity = ForecastGranularity(window.granularity)
    while current <= window.date_to:
        yield current
        if granularity is ForecastGranularity.DAY:
            current += timedelta(days=1)
        elif current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
