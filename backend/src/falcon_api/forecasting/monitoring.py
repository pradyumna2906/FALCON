"""Privacy-safe operational monitoring for forecast generation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import perf_counter

from falcon_api.forecasting.quality import ForecastEligibility
from falcon_api.forecasting.semantics import ForecastGranularity, ForecastTarget


FORECAST_OPERATION_POLICY_VERSION = "2026.1"


class ForecastMonitor:
    """Emit bounded operational fields without owners or financial values."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._logger = logger or logging.getLogger("falcon_api.forecasting")
        self._timer = timer

    def start(self) -> float:
        return self._timer()

    def record_generation(
        self,
        *,
        started_at: float,
        target: ForecastTarget,
        granularity: ForecastGranularity,
        history_periods: int,
        horizon: int,
        eligibility: ForecastEligibility,
        candidate_count: int,
        failure_count: int,
        selected_model_code: str,
    ) -> None:
        if type(history_periods) is not int or history_periods <= 0:
            raise ValueError("Forecast history periods must be positive.")
        if type(horizon) is not int or horizon <= 0:
            raise ValueError("Forecast horizon must be positive.")
        if type(candidate_count) is not int or candidate_count <= 0:
            raise ValueError("Forecast candidate count must be positive.")
        if type(failure_count) is not int or not 0 <= failure_count <= candidate_count:
            raise ValueError("Forecast failure count is invalid.")
        if not selected_model_code.strip():
            raise ValueError("Selected forecast model code cannot be blank.")

        duration_ms = max(0.0, (self._timer() - started_at) * 1000)
        self._logger.info(
            "forecast_generation_completed",
            extra={
                "forecast_policy_version": FORECAST_OPERATION_POLICY_VERSION,
                "forecast_target": ForecastTarget(target).value,
                "forecast_granularity": ForecastGranularity(granularity).value,
                "forecast_history_band": _count_band(history_periods),
                "forecast_horizon_band": _count_band(horizon),
                "forecast_eligibility": ForecastEligibility(eligibility).value,
                "forecast_candidate_count": min(candidate_count, 16),
                "forecast_failure_count": min(failure_count, 16),
                "forecast_model_family": selected_model_code.split("_", 1)[0],
                "duration_ms": round(duration_ms, 3),
            },
        )


def _count_band(value: int) -> str:
    if value <= 3:
        return "001_003"
    if value <= 12:
        return "004_012"
    if value <= 31:
        return "013_031"
    if value <= 92:
        return "032_092"
    if value <= 366:
        return "093_366"
    return "367_plus"
