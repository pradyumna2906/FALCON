"""Transparent statistical baselines for bounded financial time series."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from falcon_api.analytics.types import money
from falcon_api.forecasting.semantics import ForecastGranularity


def _validate_request(
    training_values: tuple[Decimal, ...], horizon: int, minimum: int
) -> None:
    if len(training_values) < minimum:
        raise ValueError("Baseline requires more training observations.")
    if isinstance(horizon, bool) or horizon <= 0:
        raise ValueError("Prediction horizon must be positive.")
    if any(not value.is_finite() for value in training_values):
        raise ValueError("Training values must be finite.")


def _repeat(value: Decimal, horizon: int) -> tuple[Decimal, ...]:
    return (money(value),) * horizon


@dataclass(frozen=True, slots=True)
class LastValueBaseline:
    code: str = "last_value"
    minimum_training_points: int = 1

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        _validate_request(training_values, horizon, self.minimum_training_points)
        return _repeat(training_values[-1], horizon)


@dataclass(frozen=True, slots=True)
class HistoricalMeanBaseline:
    code: str = "historical_mean"
    minimum_training_points: int = 1

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        _validate_request(training_values, horizon, self.minimum_training_points)
        value = sum(training_values) / Decimal(len(training_values))
        return _repeat(value, horizon)


@dataclass(frozen=True, slots=True)
class HistoricalMedianBaseline:
    code: str = "historical_median"
    minimum_training_points: int = 1

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        _validate_request(training_values, horizon, self.minimum_training_points)
        return _repeat(median(training_values), horizon)


@dataclass(frozen=True, slots=True)
class MovingAverageBaseline:
    window: int = 3
    code: str = "moving_average"

    def __post_init__(self) -> None:
        if isinstance(self.window, bool) or self.window <= 0:
            raise ValueError("Moving-average window must be positive.")

    @property
    def minimum_training_points(self) -> int:
        return self.window

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        _validate_request(training_values, horizon, self.minimum_training_points)
        selected = training_values[-self.window :]
        value = sum(selected) / Decimal(len(selected))
        return _repeat(value, horizon)


@dataclass(frozen=True, slots=True)
class SeasonalNaiveBaseline:
    season_length: int
    code: str = "seasonal_naive"

    def __post_init__(self) -> None:
        if isinstance(self.season_length, bool) or self.season_length <= 0:
            raise ValueError("Season length must be positive.")

    @property
    def minimum_training_points(self) -> int:
        return self.season_length

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        _validate_request(training_values, horizon, self.minimum_training_points)
        season = training_values[-self.season_length :]
        return tuple(
            money(season[index % self.season_length]) for index in range(horizon)
        )


@dataclass(frozen=True, slots=True)
class DriftBaseline:
    code: str = "drift"
    minimum_training_points: int = 2

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        _validate_request(training_values, horizon, self.minimum_training_points)
        slope = (training_values[-1] - training_values[0]) / Decimal(
            len(training_values) - 1
        )
        return tuple(
            money(training_values[-1] + slope * Decimal(step))
            for step in range(1, horizon + 1)
        )


BaselineCandidate = (
    LastValueBaseline
    | HistoricalMeanBaseline
    | HistoricalMedianBaseline
    | MovingAverageBaseline
    | SeasonalNaiveBaseline
    | DriftBaseline
)


def baseline_candidates(
    granularity: ForecastGranularity,
) -> tuple[BaselineCandidate, ...]:
    """Return the deterministic baseline registry for one calendar frequency."""
    season_length = (
        7
        if ForecastGranularity(granularity) is ForecastGranularity.DAY
        else 12
    )
    return (
        LastValueBaseline(),
        HistoricalMeanBaseline(),
        HistoricalMedianBaseline(),
        MovingAverageBaseline(),
        SeasonalNaiveBaseline(season_length=season_length),
        DriftBaseline(),
    )
