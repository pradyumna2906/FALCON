"""Calendar-window rules for owner-scoped financial analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from falcon_api.analytics.semantics import (
    MAX_ANALYTICS_RANGE_DAYS,
    AnalyticsErrorCode,
)
from falcon_api.core.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class AnalyticsPeriod:
    """One inclusive calendar-date range in the principal's timezone."""

    date_from: date
    date_to: date
    timezone: str

    def __post_init__(self) -> None:
        """Protect exported periods from invalid direct construction."""
        if self.date_to < self.date_from:
            raise ValueError("date_to must not be earlier than date_from.")
        if self.day_count > MAX_ANALYTICS_RANGE_DAYS:
            raise ValueError(
                f"Analytics ranges cannot exceed {MAX_ANALYTICS_RANGE_DAYS} days."
            )
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError(
                AnalyticsErrorCode.INVALID_TRUSTED_TIMEZONE.value
            ) from None

    @property
    def day_count(self) -> int:
        """Return the inclusive number of calendar days in the range."""
        return (self.date_to - self.date_from).days + 1


def resolve_analytics_period(
    *,
    date_from: date | None,
    date_to: date | None,
    trusted_timezone: str,
    now: datetime,
) -> AnalyticsPeriod:
    """Resolve an explicit range or the principal's current month to date."""
    try:
        timezone = ZoneInfo(trusted_timezone)
    except ZoneInfoNotFoundError:
        raise ValueError(
            AnalyticsErrorCode.INVALID_TRUSTED_TIMEZONE.value
        ) from None
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Analytics clock values must be timezone-aware.")

    local_today = now.astimezone(timezone).date()
    if date_from is None and date_to is None:
        resolved_from = local_today.replace(day=1)
        resolved_to = local_today
    elif date_from is None or date_to is None:
        raise ValueError("date_from and date_to must be supplied together.")
    else:
        resolved_from = date_from
        resolved_to = date_to

    if resolved_to < resolved_from:
        raise ValueError("date_to must not be earlier than date_from.")
    day_count = (resolved_to - resolved_from).days + 1
    if day_count > MAX_ANALYTICS_RANGE_DAYS:
        raise ValueError(
            f"Analytics ranges cannot exceed {MAX_ANALYTICS_RANGE_DAYS} days."
        )
    if resolved_to > local_today:
        raise ApplicationError(
            code=AnalyticsErrorCode.DATE_IN_FUTURE.value,
            message="Analytics date ranges cannot end in the future.",
            status_code=422,
        )
    return AnalyticsPeriod(
        date_from=resolved_from,
        date_to=resolved_to,
        timezone=trusted_timezone,
    )


def previous_period(period: AnalyticsPeriod) -> AnalyticsPeriod:
    """Return the equal-length range immediately before a selected period."""
    try:
        previous_to = period.date_from - timedelta(days=1)
        previous_from = previous_to - timedelta(days=period.day_count - 1)
    except OverflowError:
        raise ValueError(
            "The selected range has no representable previous period."
        ) from None
    return AnalyticsPeriod(
        date_from=previous_from,
        date_to=previous_to,
        timezone=period.timezone,
    )
