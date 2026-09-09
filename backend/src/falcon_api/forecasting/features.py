"""Deterministic leakage-safe features for supervised forecast candidates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from math import isfinite

from falcon_api.forecasting.semantics import ForecastGranularity


FORECAST_FEATURE_POLICY_VERSION = "2026.1"


@dataclass(frozen=True, slots=True)
class ForecastFeatureSpec:
    """Stable lag and trailing-window definition for one calendar frequency."""

    granularity: ForecastGranularity
    lags: tuple[int, ...]
    rolling_windows: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "granularity", ForecastGranularity(self.granularity))
        for values in (self.lags, self.rolling_windows):
            if not values or any(isinstance(value, bool) or value <= 0 for value in values):
                raise ValueError("Feature lags and windows must be positive integers.")
            if values != tuple(sorted(set(values))):
                raise ValueError("Feature lags and windows must be unique and ordered.")

    @property
    def minimum_history_points(self) -> int:
        return max((*self.lags, *self.rolling_windows))

    @property
    def feature_names(self) -> tuple[str, ...]:
        lag_names = tuple(f"lag_{lag}" for lag in self.lags)
        rolling_names = tuple(
            name
            for window in self.rolling_windows
            for name in (f"rolling_mean_{window}", f"rolling_std_{window}")
        )
        return (*lag_names, *rolling_names)


@dataclass(frozen=True, slots=True)
class ForecastFeatureVector:
    """One numeric feature vector derived exclusively from earlier values."""

    names: tuple[str, ...]
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ForecastSupervisedMatrix:
    """Chronological training rows with auditable target positions."""

    policy_version: str
    feature_names: tuple[str, ...]
    target_indices: tuple[int, ...]
    features: tuple[tuple[float, ...], ...]
    targets: tuple[float, ...]


def feature_spec_for(
    granularity: ForecastGranularity,
) -> ForecastFeatureSpec:
    """Return the fixed feature policy for daily or monthly history."""
    resolved = ForecastGranularity(granularity)
    if resolved is ForecastGranularity.DAY:
        return ForecastFeatureSpec(
            granularity=resolved,
            lags=(1, 7, 14, 28),
            rolling_windows=(7, 28),
        )
    return ForecastFeatureSpec(
        granularity=resolved,
        lags=(1, 2, 3, 6, 12),
        rolling_windows=(3, 6, 12),
    )


def build_feature_vector(
    *, history: tuple[Decimal, ...], spec: ForecastFeatureSpec
) -> ForecastFeatureVector:
    """Build features from history strictly preceding the predicted position."""
    _validate_values(history)
    if len(history) < spec.minimum_history_points:
        raise ValueError("Feature construction requires more historical observations.")
    values: list[float] = []
    values.extend(_to_float(history[-lag]) for lag in spec.lags)
    for window in spec.rolling_windows:
        trailing = history[-window:]
        mean = sum(trailing) / Decimal(window)
        with localcontext() as context:
            context.prec = 28
            variance = sum((value - mean) ** 2 for value in trailing) / Decimal(window)
            standard_deviation = variance.sqrt()
        values.extend((_to_float(mean), _to_float(standard_deviation)))
    return ForecastFeatureVector(names=spec.feature_names, values=tuple(values))


def build_supervised_feature_matrix(
    *, values: tuple[Decimal, ...], spec: ForecastFeatureSpec
) -> ForecastSupervisedMatrix:
    """Build ordered training rows without using each row's target as a feature."""
    _validate_values(values)
    first_target = spec.minimum_history_points
    if len(values) <= first_target:
        raise ValueError("Supervised training requires a target after feature history.")
    target_indices = tuple(range(first_target, len(values)))
    vectors = tuple(
        build_feature_vector(history=values[:target_index], spec=spec)
        for target_index in target_indices
    )
    return ForecastSupervisedMatrix(
        policy_version=FORECAST_FEATURE_POLICY_VERSION,
        feature_names=spec.feature_names,
        target_indices=target_indices,
        features=tuple(vector.values for vector in vectors),
        targets=tuple(_to_float(values[index]) for index in target_indices),
    )


def _validate_values(values: tuple[Decimal, ...]) -> None:
    if not values:
        raise ValueError("Feature construction requires non-empty history.")
    if any(not value.is_finite() for value in values):
        raise ValueError("Feature history must be finite.")


def _to_float(value: Decimal) -> float:
    converted = float(value)
    if not isfinite(converted):
        raise ValueError("Feature values must remain finite after conversion.")
    return converted
