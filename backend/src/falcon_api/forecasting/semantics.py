"""Versioned target and boundary meanings for Phase 9 forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from falcon_api.analytics.semantics import AnalyticsMetricCode, metric_definition
from falcon_api.models.enums import TransactionStatus, TransactionType


FORECASTING_CONTRACT_VERSION = "2026.1"
MIN_NORMAL_HISTORY_MONTHS = 3
MAX_FORECAST_HISTORY_DAYS = 1_827
MAX_DAILY_FORECAST_HORIZON = 366
MAX_MONTHLY_FORECAST_HORIZON = 24


class ForecastTarget(StrEnum):
    """Stable identifiers for financial values that Phase 9 may forecast."""

    GROSS_INCOME = "gross_income"
    TOTAL_EXPENSE = "total_expense"
    NET_CASH_FLOW = "net_cash_flow"
    SAVINGS_AMOUNT = "savings_amount"


class ForecastGranularity(StrEnum):
    """Calendar bucket sizes accepted by the forecasting foundation."""

    DAY = "day"
    MONTH = "month"


class ForecastErrorCode(StrEnum):
    """Stable failures reserved by the Phase 9 forecasting boundary."""

    INVALID_CURRENCY = "forecast_invalid_currency"
    INVALID_HISTORY_RANGE = "forecast_invalid_history_range"
    INVALID_DATA_CUTOFF = "forecast_invalid_data_cutoff"
    UNSUPPORTED_HORIZON = "forecast_unsupported_horizon"


@dataclass(frozen=True, slots=True)
class ForecastTargetDefinition:
    """Machine-readable meaning of one forecast target."""

    target: ForecastTarget
    source_metric: AnalyticsMetricCode
    formula: str
    transaction_types: frozenset[TransactionType]
    statuses: frozenset[TransactionStatus]
    unit: str
    description: str


_TARGET_TO_METRIC = {
    ForecastTarget.GROSS_INCOME: AnalyticsMetricCode.GROSS_INCOME,
    ForecastTarget.TOTAL_EXPENSE: AnalyticsMetricCode.TOTAL_EXPENSE,
    ForecastTarget.NET_CASH_FLOW: AnalyticsMetricCode.NET_CASH_FLOW,
    ForecastTarget.SAVINGS_AMOUNT: AnalyticsMetricCode.SAVINGS_AMOUNT,
}

_TARGET_DEFINITIONS = {
    target: ForecastTargetDefinition(
        target=target,
        source_metric=metric_code,
        formula=metric_definition(metric_code).formula,
        transaction_types=metric_definition(metric_code).transaction_types,
        statuses=metric_definition(metric_code).statuses,
        unit=metric_definition(metric_code).unit,
        description=metric_definition(metric_code).description,
    )
    for target, metric_code in _TARGET_TO_METRIC.items()
}

FORECAST_TARGET_DEFINITIONS = MappingProxyType(_TARGET_DEFINITIONS)


def forecast_target_definition(target: ForecastTarget) -> ForecastTargetDefinition:
    """Return the immutable definition for one supported forecast target."""
    return FORECAST_TARGET_DEFINITIONS[ForecastTarget(target)]


def normalize_forecast_currency(value: str) -> str:
    """Return one uppercase ISO-style currency without performing conversion."""
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError(ForecastErrorCode.INVALID_CURRENCY.value)
    return normalized


def validate_forecast_horizon(
    *, granularity: ForecastGranularity, horizon: int
) -> int:
    """Validate and return a bounded number of future calendar buckets."""
    resolved_granularity = ForecastGranularity(granularity)
    maximum = (
        MAX_DAILY_FORECAST_HORIZON
        if resolved_granularity is ForecastGranularity.DAY
        else MAX_MONTHLY_FORECAST_HORIZON
    )
    if isinstance(horizon, bool) or not 1 <= horizon <= maximum:
        raise ValueError(ForecastErrorCode.UNSUPPORTED_HORIZON.value)
    return horizon
