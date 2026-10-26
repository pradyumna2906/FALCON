"""Tests for deterministic recursive CPU XGBoost forecasting."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from falcon_api.forecasting import (
    ForecastCandidateFitError,
    ForecastCandidateUnavailableError,
    ForecastGranularity,
    XGBoostCandidate,
)
from falcon_api.forecasting import boosting


def test_xgboost_candidate_runs_with_pinned_cpu_dependency() -> None:
    candidate = XGBoostCandidate(ForecastGranularity.MONTH, estimators=8)
    training = tuple(Decimal(100 + index * 2) for index in range(20))
    result = candidate.predict(training, 2)
    assert candidate.code == "xgboost_lagged_month"
    assert candidate.minimum_training_points == 20
    assert len(result) == 2
    assert all(value.is_finite() and value.as_tuple().exponent == -4 for value in result)


class _RecursiveRegressor:
    def __init__(self, **kwargs: object) -> None:
        assert kwargs["random_state"] == 2026

    def fit(self, features: object, targets: object) -> None:
        assert len(features) == len(targets)  # type: ignore[arg-type]

    def predict(self, rows: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
        return (rows[0][0] + 1.0,)


def test_xgboost_multistep_forecast_is_recursive_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        boosting,
        "import_module",
        lambda name: SimpleNamespace(XGBRegressor=_RecursiveRegressor),
    )
    candidate = XGBoostCandidate(ForecastGranularity.MONTH)
    training = tuple(Decimal(value) for value in range(1, 21))
    assert candidate.predict(training, 3) == (
        Decimal("21.0000"),
        Decimal("22.0000"),
        Decimal("23.0000"),
    )


def test_xgboost_optional_dependency_and_model_failure_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = XGBoostCandidate(ForecastGranularity.MONTH)
    training = tuple(Decimal(value) for value in range(20))
    monkeypatch.setattr(
        boosting,
        "import_module",
        lambda name: (_ for _ in ()).throw(ModuleNotFoundError(name)),
    )
    with pytest.raises(ForecastCandidateUnavailableError, match="unavailable"):
        candidate.predict(training, 1)

    class BrokenRegressor(_RecursiveRegressor):
        def predict(self, rows: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
            return (float("nan"),)

    monkeypatch.setattr(
        boosting,
        "import_module",
        lambda name: SimpleNamespace(XGBRegressor=BrokenRegressor),
    )
    with pytest.raises(ForecastCandidateFitError, match="unsafe"):
        candidate.predict(training, 1)

    class FitBrokenRegressor(_RecursiveRegressor):
        def fit(self, features: object, targets: object) -> None:
            raise RuntimeError("fit failed")

    monkeypatch.setattr(
        boosting,
        "import_module",
        lambda name: SimpleNamespace(XGBRegressor=FitBrokenRegressor),
    )
    with pytest.raises(ForecastCandidateFitError, match="fitting failed"):
        candidate.predict(training, 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"estimators": 0},
        {"estimators": True},
        {"maximum_depth": 0},
        {"learning_rate": 0},
        {"learning_rate": 1.1},
    ],
)
def test_xgboost_hyperparameters_are_bounded(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        XGBoostCandidate(ForecastGranularity.DAY, **kwargs)  # type: ignore[arg-type]


def test_xgboost_requires_enough_history_before_importing_dependency() -> None:
    candidate = XGBoostCandidate(ForecastGranularity.DAY)
    with pytest.raises(ValueError, match="more training"):
        candidate.predict(tuple(Decimal(value) for value in range(35)), 1)

    valid_length = tuple(Decimal(value) for value in range(36))
    with pytest.raises(ValueError, match="horizon"):
        candidate.predict(valid_length, 0)
    nonfinite = (*valid_length[:-1], Decimal("NaN"))
    with pytest.raises(ValueError, match="finite"):
        candidate.predict(nonfinite, 1)
