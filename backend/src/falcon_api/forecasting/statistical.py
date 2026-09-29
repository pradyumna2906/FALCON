"""Lazy Statsmodels and optional Prophet forecast candidate adapters."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from importlib import import_module
from warnings import catch_warnings, simplefilter

from falcon_api.forecasting.candidates import (
    ForecastCandidateFitError,
    ForecastCandidateUnavailableError,
    normalize_candidate_predictions,
    validate_candidate_request,
)
from falcon_api.forecasting.semantics import ForecastGranularity


@dataclass(frozen=True, slots=True)
class ArimaCandidate:
    """Bounded non-seasonal ARIMA candidate backed by Statsmodels."""

    order: tuple[int, int, int] = (1, 1, 1)

    def __post_init__(self) -> None:
        if len(self.order) != 3 or any(
            isinstance(value, bool) or value < 0 for value in self.order
        ):
            raise ValueError("ARIMA order must contain three non-negative integers.")

    @property
    def code(self) -> str:
        return "arima_" + "_".join(str(value) for value in self.order)

    @property
    def minimum_training_points(self) -> int:
        return max(8, sum(self.order) + 3)

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        validate_candidate_request(
            training_values, horizon, self.minimum_training_points
        )
        try:
            arima = import_module("statsmodels.tsa.arima.model").ARIMA
            with catch_warnings():
                simplefilter("ignore")
                result = arima(
                    tuple(float(value) for value in training_values),
                    order=self.order,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                ).fit()
                predicted = result.forecast(steps=horizon)
            return normalize_candidate_predictions(predicted, horizon=horizon)
        except (ForecastCandidateFitError, ForecastCandidateUnavailableError):
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            raise ForecastCandidateUnavailableError(
                "Statsmodels ARIMA is unavailable."
            ) from exc
        except Exception as exc:
            raise ForecastCandidateFitError("ARIMA fitting failed safely.") from exc


@dataclass(frozen=True, slots=True)
class SarimaCandidate:
    """Calendar-frequency seasonal ARIMA candidate backed by Statsmodels."""

    granularity: ForecastGranularity
    order: tuple[int, int, int] = (1, 1, 0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "granularity", ForecastGranularity(self.granularity))
        if len(self.order) != 3 or any(
            isinstance(value, bool) or value < 0 for value in self.order
        ):
            raise ValueError("SARIMA order must contain three non-negative integers.")

    @property
    def season_length(self) -> int:
        return 7 if self.granularity is ForecastGranularity.DAY else 12

    @property
    def seasonal_order(self) -> tuple[int, int, int, int]:
        return (1, 0, 0, self.season_length)

    @property
    def code(self) -> str:
        return f"sarima_{self.granularity.value}_{self.season_length}"

    @property
    def minimum_training_points(self) -> int:
        return (2 * self.season_length) + 3

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        validate_candidate_request(
            training_values, horizon, self.minimum_training_points
        )
        try:
            sarimax = import_module("statsmodels.tsa.statespace.sarimax").SARIMAX
            with catch_warnings():
                simplefilter("ignore")
                result = sarimax(
                    tuple(float(value) for value in training_values),
                    order=self.order,
                    seasonal_order=self.seasonal_order,
                    trend="n",
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                ).fit(disp=False)
                predicted = result.forecast(steps=horizon)
            return normalize_candidate_predictions(predicted, horizon=horizon)
        except (ForecastCandidateFitError, ForecastCandidateUnavailableError):
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            raise ForecastCandidateUnavailableError(
                "Statsmodels SARIMA is unavailable."
            ) from exc
        except Exception as exc:
            raise ForecastCandidateFitError("SARIMA fitting failed safely.") from exc


@dataclass(frozen=True, slots=True)
class ProphetCandidate:
    """Optional Prophet adapter using synthetic dates for an already bucketed series."""

    granularity: ForecastGranularity

    def __post_init__(self) -> None:
        object.__setattr__(self, "granularity", ForecastGranularity(self.granularity))

    @property
    def code(self) -> str:
        return f"prophet_{self.granularity.value}"

    @property
    def minimum_training_points(self) -> int:
        return 14 if self.granularity is ForecastGranularity.DAY else 12

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        validate_candidate_request(
            training_values, horizon, self.minimum_training_points
        )
        try:
            pandas = import_module("pandas")
            prophet_type = import_module("prophet").Prophet
        except (ImportError, ModuleNotFoundError) as exc:
            raise ForecastCandidateUnavailableError(
                "Optional Prophet dependency is unavailable."
            ) from exc
        frequency = "D" if self.granularity is ForecastGranularity.DAY else "MS"
        dates = pandas.date_range("2000-01-01", periods=len(training_values), freq=frequency)
        history = pandas.DataFrame(
            {"ds": dates, "y": tuple(float(value) for value in training_values)}
        )
        try:
            with catch_warnings():
                simplefilter("ignore")
                model = prophet_type(
                    weekly_seasonality=self.granularity is ForecastGranularity.DAY,
                    yearly_seasonality=False,
                    daily_seasonality=False,
                    uncertainty_samples=0,
                )
                model.fit(history)
                future_dates = pandas.date_range(
                    dates[-1], periods=horizon + 1, freq=frequency
                )[1:]
                result = model.predict(pandas.DataFrame({"ds": future_dates}))
            return normalize_candidate_predictions(result["yhat"], horizon=horizon)
        except ForecastCandidateFitError:
            raise
        except Exception as exc:
            raise ForecastCandidateFitError("Prophet fitting failed safely.") from exc
