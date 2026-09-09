"""Tests for bounded Statsmodels and optional Prophet candidates."""

from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from falcon_api.forecasting import (
    ArimaCandidate,
    ForecastCandidateFitError,
    ForecastCandidateUnavailableError,
    ForecastGranularity,
    ProphetCandidate,
    SarimaCandidate,
)
from falcon_api.forecasting import statistical


def test_arima_candidate_produces_finite_money_predictions() -> None:
    candidate = ArimaCandidate(order=(1, 1, 0))
    training = tuple(Decimal(value) for value in range(1, 13))
    result = candidate.predict(training, 2)
    assert candidate.code == "arima_1_1_0"
    assert len(result) == 2
    assert all(value.is_finite() and value.as_tuple().exponent == -4 for value in result)


def test_sarima_candidate_uses_frequency_specific_seasonality() -> None:
    candidate = SarimaCandidate(ForecastGranularity.DAY)
    training = tuple(Decimal(10 + (index % 7)) for index in range(21))
    result = candidate.predict(training, 2)
    assert candidate.season_length == 7
    assert candidate.seasonal_order == (1, 0, 0, 7)
    assert candidate.code == "sarima_day_7"
    assert len(result) == 2


class _FakeProphet:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def fit(self, history: pd.DataFrame) -> None:
        assert tuple(history.columns) == ("ds", "y")

    def predict(self, future: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"yhat": [42.125] * len(future)})


def test_prophet_adapter_is_lazy_and_uses_only_future_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = statistical.import_module

    def fake_import(name: str) -> object:
        if name == "prophet":
            return SimpleNamespace(Prophet=_FakeProphet)
        return original_import(name)

    monkeypatch.setattr(statistical, "import_module", fake_import)
    candidate = ProphetCandidate(ForecastGranularity.MONTH)
    training = tuple(Decimal(value) for value in range(1, 13))
    assert candidate.predict(training, 2) == (
        Decimal("42.1250"),
        Decimal("42.1250"),
    )
    assert ProphetCandidate(ForecastGranularity.DAY).minimum_training_points == 14


def test_prophet_absence_does_not_block_other_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = statistical.import_module

    def missing_prophet(name: str) -> object:
        if name == "prophet":
            raise ModuleNotFoundError(name)
        return original_import(name)

    monkeypatch.setattr(statistical, "import_module", missing_prophet)
    candidate = ProphetCandidate(ForecastGranularity.MONTH)
    with pytest.raises(ForecastCandidateUnavailableError, match="Optional Prophet"):
        candidate.predict(tuple(Decimal(value) for value in range(12)), 1)


@pytest.mark.parametrize("candidate", [ArimaCandidate(), SarimaCandidate("month")])
def test_statistical_candidates_reject_insufficient_history(candidate: object) -> None:
    with pytest.raises(ValueError, match="more training"):
        candidate.predict((Decimal("1"),), 1)  # type: ignore[attr-defined]


def test_invalid_statistical_orders_and_unsafe_output_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="order"):
        ArimaCandidate(order=(1, -1, 0))
    with pytest.raises(ValueError, match="order"):
        SarimaCandidate(ForecastGranularity.DAY, order=(1, True, 0))

    class BrokenProphet(_FakeProphet):
        def predict(self, future: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({"yhat": [float("nan")] * len(future)})

    original_import = statistical.import_module
    monkeypatch.setattr(
        statistical,
        "import_module",
        lambda name: SimpleNamespace(Prophet=BrokenProphet)
        if name == "prophet"
        else original_import(name),
    )
    with pytest.raises(ForecastCandidateFitError, match="unsafe"):
        ProphetCandidate(ForecastGranularity.MONTH).predict(
            tuple(Decimal(value) for value in range(12)), 1
        )


@pytest.mark.parametrize(
    "candidate",
    [ArimaCandidate(order=(1, 1, 0)), SarimaCandidate(ForecastGranularity.DAY)],
)
def test_missing_statsmodels_is_an_explicit_unavailable_candidate(
    candidate: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        statistical,
        "import_module",
        lambda name: (_ for _ in ()).throw(ModuleNotFoundError(name)),
    )
    training = tuple(
        Decimal(value)
        for value in range(candidate.minimum_training_points)  # type: ignore[attr-defined]
    )
    with pytest.raises(ForecastCandidateUnavailableError, match="unavailable"):
        candidate.predict(training, 1)  # type: ignore[attr-defined]


def test_statistical_fit_failures_are_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = statistical.import_module

    class BrokenModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("fit failed")

    monkeypatch.setattr(
        statistical,
        "import_module",
        lambda name: SimpleNamespace(ARIMA=BrokenModel, SARIMAX=BrokenModel),
    )
    arima = ArimaCandidate(order=(1, 1, 0))
    with pytest.raises(ForecastCandidateFitError, match="ARIMA fitting"):
        arima.predict(tuple(Decimal(value) for value in range(8)), 1)
    sarima = SarimaCandidate(ForecastGranularity.DAY)
    with pytest.raises(ForecastCandidateFitError, match="SARIMA fitting"):
        sarima.predict(tuple(Decimal(value) for value in range(17)), 1)

    class FitBrokenProphet(_FakeProphet):
        def fit(self, history: pd.DataFrame) -> None:
            raise RuntimeError("fit failed")

    monkeypatch.setattr(
        statistical,
        "import_module",
        lambda name: SimpleNamespace(Prophet=FitBrokenProphet)
        if name == "prophet"
        else original_import(name),
    )
    with pytest.raises(ForecastCandidateFitError, match="Prophet fitting"):
        ProphetCandidate(ForecastGranularity.MONTH).predict(
            tuple(Decimal(value) for value in range(12)), 1
        )
