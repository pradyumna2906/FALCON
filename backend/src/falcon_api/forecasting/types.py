"""Exact internal types for leakage-safe forecasting source series."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from falcon_api.analytics.types import money
from falcon_api.forecasting.semantics import ForecastGranularity, ForecastTarget


@dataclass(frozen=True, slots=True)
class ForecastSourceBucket:
    """One observed aggregate returned by the owner-scoped repository."""

    period_start: date
    gross_income: Decimal
    total_expense: Decimal
    transaction_count: int
    source_last_updated_at: datetime

    def __post_init__(self) -> None:
        if self.transaction_count <= 0:
            raise ValueError("Observed source buckets require a positive row count.")
        if self.gross_income < 0 or self.total_expense < 0:
            raise ValueError("Source income and expense totals cannot be negative.")
        if (
            self.source_last_updated_at.tzinfo is None
            or self.source_last_updated_at.utcoffset() is None
        ):
            raise ValueError("Source update timestamps must be timezone-aware.")

    @property
    def net_cash_flow(self) -> Decimal:
        return money(self.gross_income - self.total_expense)


@dataclass(frozen=True, slots=True)
class ForecastSeriesPoint:
    """One chronologically complete model-input observation."""

    period_start: date
    value: Decimal
    transaction_count: int
    is_observed: bool


@dataclass(frozen=True, slots=True)
class ForecastSeries:
    """One target series with immutable source and leakage boundaries."""

    target: ForecastTarget
    granularity: ForecastGranularity
    currency: str
    history_start: date
    history_end: date
    data_cutoff_at: datetime
    points: tuple[ForecastSeriesPoint, ...]
    source_last_updated_at: datetime | None

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("Forecast series must contain calendar-complete points.")
        starts = tuple(point.period_start for point in self.points)
        if starts != tuple(sorted(starts)) or len(starts) != len(set(starts)):
            raise ValueError("Forecast series points must be unique and chronological.")

    @property
    def observed_period_count(self) -> int:
        return sum(point.is_observed for point in self.points)

    @property
    def transaction_count(self) -> int:
        return sum(point.transaction_count for point in self.points)
