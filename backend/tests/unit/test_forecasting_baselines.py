"""Tests for deterministic, transparent statistical forecast baselines."""

from decimal import Decimal

import pytest

from falcon_api.forecasting import (
    DriftBaseline,
    ForecastGranularity,
    HistoricalMeanBaseline,
    HistoricalMedianBaseline,
    LastValueBaseline,
    MovingAverageBaseline,
    SeasonalNaiveBaseline,
    baseline_candidates,
)


_VALUES = (Decimal("10"), Decimal("20"), Decimal("30"))


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (LastValueBaseline(), (Decimal("30.0000"),) * 2),
        (HistoricalMeanBaseline(), (Decimal("20.0000"),) * 2),
        (HistoricalMedianBaseline(), (Decimal("20.0000"),) * 2),
        (MovingAverageBaseline(window=2), (Decimal("25.0000"),) * 2),
        (DriftBaseline(), (Decimal("40.0000"), Decimal("50.0000"))),
    ],
)
def test_nonseasonal_baselines_produce_exact_expected_values(
    candidate: object, expected: tuple[Decimal, ...]
) -> None:
    assert candidate.predict(_VALUES, 2) == expected  # type: ignore[attr-defined]


def test_seasonal_naive_repeats_the_latest_complete_season() -> None:
    candidate = SeasonalNaiveBaseline(season_length=3)
    training = tuple(Decimal(value) for value in (1, 2, 3, 4, 5, 6))
    assert candidate.predict(training, 5) == tuple(
        Decimal(value)
        for value in ("4.0000", "5.0000", "6.0000", "4.0000", "5.0000")
    )


def test_registry_is_stable_and_uses_calendar_appropriate_seasons() -> None:
    daily = baseline_candidates(ForecastGranularity.DAY)
    monthly = baseline_candidates(ForecastGranularity.MONTH)
    expected_codes = (
        "last_value",
        "historical_mean",
        "historical_median",
        "moving_average",
        "seasonal_naive",
        "drift",
    )
    assert tuple(candidate.code for candidate in daily) == expected_codes
    assert tuple(candidate.code for candidate in monthly) == expected_codes
    assert daily[4].minimum_training_points == 7
    assert monthly[4].minimum_training_points == 12


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: MovingAverageBaseline(window=0),
        lambda: MovingAverageBaseline(window=True),
        lambda: SeasonalNaiveBaseline(season_length=0),
        lambda: SeasonalNaiveBaseline(season_length=True),
    ],
)
def test_configurable_baselines_reject_invalid_windows(constructor: object) -> None:
    with pytest.raises(ValueError, match="positive"):
        constructor()  # type: ignore[operator]


@pytest.mark.parametrize(
    ("candidate", "training", "horizon", "message"),
    [
        (LastValueBaseline(), (), 1, "more training"),
        (MovingAverageBaseline(window=3), _VALUES[:2], 1, "more training"),
        (LastValueBaseline(), _VALUES, 0, "horizon"),
        (LastValueBaseline(), _VALUES, True, "horizon"),
        (
            LastValueBaseline(),
            (Decimal("NaN"),),
            1,
            "finite",
        ),
    ],
)
def test_baselines_reject_unsafe_prediction_requests(
    candidate: object,
    training: tuple[Decimal, ...],
    horizon: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        candidate.predict(training, horizon)  # type: ignore[attr-defined]
