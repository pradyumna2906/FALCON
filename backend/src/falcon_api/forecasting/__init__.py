"""Versioned forecasting contracts and source-series foundation."""

from falcon_api.forecasting.periods import ForecastHistoryWindow
from falcon_api.forecasting.repository import ForecastingRepository
from falcon_api.forecasting.semantics import (
    FORECASTING_CONTRACT_VERSION,
    FORECAST_TARGET_DEFINITIONS,
    MAX_DAILY_FORECAST_HORIZON,
    MAX_FORECAST_HISTORY_DAYS,
    MAX_MONTHLY_FORECAST_HORIZON,
    MIN_NORMAL_HISTORY_MONTHS,
    ForecastErrorCode,
    ForecastGranularity,
    ForecastTarget,
    ForecastTargetDefinition,
    forecast_target_definition,
    normalize_forecast_currency,
    validate_forecast_horizon,
)
from falcon_api.forecasting.series import build_forecast_series
from falcon_api.forecasting.types import (
    ForecastSeries,
    ForecastSeriesPoint,
    ForecastSourceBucket,
)

__all__ = (
    "FORECASTING_CONTRACT_VERSION",
    "FORECAST_TARGET_DEFINITIONS",
    "MAX_DAILY_FORECAST_HORIZON",
    "MAX_FORECAST_HISTORY_DAYS",
    "MAX_MONTHLY_FORECAST_HORIZON",
    "MIN_NORMAL_HISTORY_MONTHS",
    "ForecastErrorCode",
    "ForecastGranularity",
    "ForecastHistoryWindow",
    "ForecastSeries",
    "ForecastSeriesPoint",
    "ForecastSourceBucket",
    "ForecastTarget",
    "ForecastTargetDefinition",
    "ForecastingRepository",
    "build_forecast_series",
    "forecast_target_definition",
    "normalize_forecast_currency",
    "validate_forecast_horizon",
)
