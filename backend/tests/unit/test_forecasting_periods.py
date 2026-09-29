"""Tests for immutable forecasting history and cutoff windows."""

from datetime import UTC, date, datetime

import pytest

from falcon_api.forecasting import ForecastGranularity, ForecastHistoryWindow


_CUTOFF = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def test_daily_history_window_is_inclusive_and_cutoff_safe() -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 7),
        timezone="Asia/Kolkata",
        granularity=ForecastGranularity.DAY,
        data_cutoff_at=_CUTOFF,
    )
    assert window.day_count == 7


def test_monthly_history_requires_complete_calendar_months() -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 8, 31),
        timezone="UTC",
        granularity=ForecastGranularity.MONTH,
        data_cutoff_at=_CUTOFF,
    )
    assert window.day_count == 92

    for date_from, date_to in (
        (date(2026, 6, 2), date(2026, 8, 31)),
        (date(2026, 6, 1), date(2026, 8, 30)),
    ):
        with pytest.raises(ValueError, match="forecast_invalid_history_range"):
            ForecastHistoryWindow(
                date_from=date_from,
                date_to=date_to,
                timezone="UTC",
                granularity=ForecastGranularity.MONTH,
                data_cutoff_at=_CUTOFF,
            )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"date_from": date(2026, 9, 8), "date_to": date(2026, 9, 7)},
        {"date_from": date(2021, 9, 1), "date_to": date(2026, 9, 2)},
    ],
)
def test_invalid_history_ranges_are_rejected(kwargs: dict[str, date]) -> None:
    with pytest.raises(ValueError, match="forecast_invalid_history_range"):
        ForecastHistoryWindow(
            timezone="UTC",
            granularity=ForecastGranularity.DAY,
            data_cutoff_at=_CUTOFF,
            **kwargs,
        )


def test_history_cannot_cross_the_trusted_local_cutoff_date() -> None:
    with pytest.raises(ValueError, match="forecast_invalid_data_cutoff"):
        ForecastHistoryWindow(
            date_from=date(2026, 9, 7),
            date_to=date(2026, 9, 8),
            timezone="Asia/Kolkata",
            granularity=ForecastGranularity.DAY,
            data_cutoff_at=_CUTOFF,
        )


def test_cutoff_and_timezone_must_be_trusted() -> None:
    with pytest.raises(ValueError, match="forecast_invalid_data_cutoff"):
        ForecastHistoryWindow(
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 7),
            timezone="UTC",
            granularity=ForecastGranularity.DAY,
            data_cutoff_at=datetime(2026, 9, 7),
        )
    with pytest.raises(ValueError, match="forecast_invalid_trusted_timezone"):
        ForecastHistoryWindow(
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 7),
            timezone="Invalid/Timezone",
            granularity=ForecastGranularity.DAY,
            data_cutoff_at=_CUTOFF,
        )
