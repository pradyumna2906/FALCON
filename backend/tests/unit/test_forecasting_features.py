"""Tests for deterministic leakage-safe forecast feature construction."""

from decimal import Decimal

import pytest

from falcon_api.forecasting import (
    FORECAST_FEATURE_POLICY_VERSION,
    ForecastFeatureSpec,
    ForecastGranularity,
    build_feature_vector,
    build_supervised_feature_matrix,
    feature_spec_for,
)


def test_frequency_feature_specs_are_fixed_and_auditable() -> None:
    daily = feature_spec_for(ForecastGranularity.DAY)
    monthly = feature_spec_for(ForecastGranularity.MONTH)
    assert daily.lags == (1, 7, 14, 28)
    assert daily.rolling_windows == (7, 28)
    assert daily.minimum_history_points == 28
    assert monthly.lags == (1, 2, 3, 6, 12)
    assert monthly.rolling_windows == (3, 6, 12)
    assert monthly.minimum_history_points == 12
    assert monthly.feature_names == (
        "lag_1",
        "lag_2",
        "lag_3",
        "lag_6",
        "lag_12",
        "rolling_mean_3",
        "rolling_std_3",
        "rolling_mean_6",
        "rolling_std_6",
        "rolling_mean_12",
        "rolling_std_12",
    )


def test_feature_vector_uses_only_trailing_history() -> None:
    spec = ForecastFeatureSpec(
        granularity=ForecastGranularity.MONTH,
        lags=(1, 2),
        rolling_windows=(2,),
    )
    vector = build_feature_vector(
        history=(Decimal("1"), Decimal("2"), Decimal("3")), spec=spec
    )
    assert vector.names == (
        "lag_1",
        "lag_2",
        "rolling_mean_2",
        "rolling_std_2",
    )
    assert vector.values == (3.0, 2.0, 2.5, 0.5)


def test_supervised_matrix_records_chronological_target_positions() -> None:
    spec = ForecastFeatureSpec(
        granularity=ForecastGranularity.MONTH,
        lags=(1, 2),
        rolling_windows=(2,),
    )
    matrix = build_supervised_feature_matrix(
        values=tuple(Decimal(value) for value in (1, 2, 3, 4)), spec=spec
    )
    assert matrix.policy_version == FORECAST_FEATURE_POLICY_VERSION
    assert matrix.target_indices == (2, 3)
    assert matrix.features == (
        (2.0, 1.0, 1.5, 0.5),
        (3.0, 2.0, 2.5, 0.5),
    )
    assert matrix.targets == (3.0, 4.0)


@pytest.mark.parametrize(
    ("lags", "windows"),
    [
        ((), (1,)),
        ((1,), ()),
        ((0,), (1,)),
        ((True,), (1,)),
        ((2, 1), (1,)),
        ((1, 1), (1,)),
    ],
)
def test_feature_spec_rejects_ambiguous_or_invalid_windows(
    lags: tuple[int, ...], windows: tuple[int, ...]
) -> None:
    with pytest.raises(ValueError):
        ForecastFeatureSpec(
            granularity=ForecastGranularity.DAY,
            lags=lags,
            rolling_windows=windows,
        )


def test_feature_construction_rejects_unsafe_history() -> None:
    spec = ForecastFeatureSpec(
        granularity=ForecastGranularity.DAY,
        lags=(1, 2),
        rolling_windows=(2,),
    )
    with pytest.raises(ValueError, match="non-empty"):
        build_feature_vector(history=(), spec=spec)
    with pytest.raises(ValueError, match="finite"):
        build_feature_vector(
            history=(Decimal("1"), Decimal("NaN")), spec=spec
        )
    with pytest.raises(ValueError, match="more historical"):
        build_feature_vector(history=(Decimal("1"),), spec=spec)
    with pytest.raises(ValueError, match="target after"):
        build_supervised_feature_matrix(
            values=(Decimal("1"), Decimal("2")), spec=spec
        )
    with pytest.raises(ValueError, match="remain finite"):
        build_feature_vector(
            history=(Decimal("1e10000"), Decimal("1e10000")), spec=spec
        )
