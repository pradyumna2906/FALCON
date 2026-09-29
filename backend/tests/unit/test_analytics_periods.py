"""Tests for trusted timezone and comparison-period semantics."""

from datetime import date, datetime, timezone

import pytest

from falcon_api.analytics.periods import (
    AnalyticsPeriod,
    previous_period,
    resolve_analytics_period,
)
from falcon_api.core.errors import ApplicationError


def test_default_period_is_current_month_in_trusted_timezone() -> None:
    period = resolve_analytics_period(
        date_from=None,
        date_to=None,
        trusted_timezone="Asia/Kolkata",
        now=datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc),
    )

    assert period == AnalyticsPeriod(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 1),
        timezone="Asia/Kolkata",
    )
    assert period.day_count == 1


def test_explicit_dates_are_inclusive_and_never_timezone_shifted() -> None:
    period = resolve_analytics_period(
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        trusted_timezone="America/New_York",
        now=datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc),
    )

    assert period.date_from == date(2026, 8, 1)
    assert period.date_to == date(2026, 8, 31)
    assert period.day_count == 31


def test_previous_period_has_same_length_and_no_overlap() -> None:
    selected = AnalyticsPeriod(
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 24),
        timezone="Asia/Kolkata",
    )

    comparison = previous_period(selected)

    assert comparison == AnalyticsPeriod(
        date_from=date(2026, 7, 26),
        date_to=date(2026, 8, 9),
        timezone="Asia/Kolkata",
    )
    assert comparison.day_count == selected.day_count


def test_exported_period_rejects_invalid_direct_construction() -> None:
    with pytest.raises(ValueError, match="earlier"):
        AnalyticsPeriod(
            date_from=date(2026, 8, 2),
            date_to=date(2026, 8, 1),
            timezone="UTC",
        )
    with pytest.raises(ValueError, match="366"):
        AnalyticsPeriod(
            date_from=date(2025, 1, 1),
            date_to=date(2026, 1, 2),
            timezone="UTC",
        )
    with pytest.raises(ValueError, match="invalid_trusted_timezone"):
        AnalyticsPeriod(
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 1),
            timezone="Invalid/Timezone",
        )


def test_previous_period_rejects_calendar_underflow() -> None:
    selected = AnalyticsPeriod(
        date_from=date.min,
        date_to=date.min,
        timezone="UTC",
    )

    with pytest.raises(ValueError, match="no representable previous period"):
        previous_period(selected)


def test_future_end_date_uses_trusted_local_today() -> None:
    with pytest.raises(ApplicationError) as captured:
        resolve_analytics_period(
            date_from=date(2026, 8, 1),
            date_to=date(2026, 8, 25),
            trusted_timezone="Asia/Kolkata",
            now=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        )

    assert captured.value.code == "analytics_date_in_future"
    assert captured.value.status_code == 422


@pytest.mark.parametrize(
    "kwargs",
    [
        {"date_from": date(2026, 8, 1), "date_to": None},
        {"date_from": date(2026, 8, 2), "date_to": date(2026, 8, 1)},
        {"date_from": date(2025, 1, 1), "date_to": date(2026, 1, 2)},
    ],
)
def test_period_resolver_defensively_rejects_invalid_ranges(
    kwargs: dict[str, date | None],
) -> None:
    with pytest.raises(ValueError):
        resolve_analytics_period(
            trusted_timezone="UTC",
            now=datetime(2026, 8, 24, tzinfo=timezone.utc),
            **kwargs,
        )


def test_period_resolver_rejects_invalid_trusted_context() -> None:
    with pytest.raises(ValueError, match="invalid_trusted_timezone"):
        resolve_analytics_period(
            date_from=None,
            date_to=None,
            trusted_timezone="Invalid/Timezone",
            now=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_analytics_period(
            date_from=None,
            date_to=None,
            trusted_timezone="UTC",
            now=datetime(2026, 8, 24),
        )
