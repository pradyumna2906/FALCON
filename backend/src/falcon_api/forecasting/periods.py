"""Calendar and cutoff rules for Phase 9 source history."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from falcon_api.forecasting.semantics import (
    MAX_FORECAST_HISTORY_DAYS,
    ForecastErrorCode,
    ForecastGranularity,
)


@dataclass(frozen=True, slots=True)
class ForecastHistoryWindow:
    """Inclusive model-input history frozen at a trusted instant."""

    date_from: date
    date_to: date
    timezone: str
    granularity: ForecastGranularity
    data_cutoff_at: datetime

    def __post_init__(self) -> None:
        if self.date_to < self.date_from:
            raise ValueError(ForecastErrorCode.INVALID_HISTORY_RANGE.value)
        if self.day_count > MAX_FORECAST_HISTORY_DAYS:
            raise ValueError(ForecastErrorCode.INVALID_HISTORY_RANGE.value)
        try:
            trusted_timezone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("forecast_invalid_trusted_timezone") from None
        if (
            self.data_cutoff_at.tzinfo is None
            or self.data_cutoff_at.utcoffset() is None
        ):
            raise ValueError(ForecastErrorCode.INVALID_DATA_CUTOFF.value)
        local_cutoff_date = self.data_cutoff_at.astimezone(trusted_timezone).date()
        if self.date_to > local_cutoff_date:
            raise ValueError(ForecastErrorCode.INVALID_DATA_CUTOFF.value)
        resolved_granularity = ForecastGranularity(self.granularity)
        if resolved_granularity is ForecastGranularity.MONTH:
            if self.date_from.day != 1 or self.date_to.day != calendar.monthrange(
                self.date_to.year, self.date_to.month
            )[1]:
                raise ValueError(ForecastErrorCode.INVALID_HISTORY_RANGE.value)

    @property
    def day_count(self) -> int:
        return (self.date_to - self.date_from).days + 1
