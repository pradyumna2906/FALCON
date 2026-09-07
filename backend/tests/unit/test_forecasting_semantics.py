"""Contract tests for Phase 9 forecasting meanings and dependency boundaries."""

from pathlib import Path
from types import MappingProxyType

import pytest

from falcon_api.analytics import AnalyticsMetricCode
from falcon_api.forecasting import (
    FORECASTING_CONTRACT_VERSION,
    FORECAST_TARGET_DEFINITIONS,
    MAX_DAILY_FORECAST_HORIZON,
    MAX_MONTHLY_FORECAST_HORIZON,
    MIN_NORMAL_HISTORY_MONTHS,
    ForecastGranularity,
    ForecastTarget,
    forecast_target_definition,
    normalize_forecast_currency,
    validate_forecast_horizon,
)
from falcon_api.models.enums import TransactionStatus, TransactionType


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_target_registry_is_versioned_complete_and_immutable() -> None:
    assert FORECASTING_CONTRACT_VERSION == "2026.1"
    assert MIN_NORMAL_HISTORY_MONTHS == 3
    assert isinstance(FORECAST_TARGET_DEFINITIONS, MappingProxyType)
    assert set(FORECAST_TARGET_DEFINITIONS) == set(ForecastTarget)
    with pytest.raises(TypeError):
        FORECAST_TARGET_DEFINITIONS[ForecastTarget.GROSS_INCOME] = object()  # type: ignore[index,assignment]


@pytest.mark.parametrize(
    ("target", "metric"),
    [
        (ForecastTarget.GROSS_INCOME, AnalyticsMetricCode.GROSS_INCOME),
        (ForecastTarget.TOTAL_EXPENSE, AnalyticsMetricCode.TOTAL_EXPENSE),
        (ForecastTarget.NET_CASH_FLOW, AnalyticsMetricCode.NET_CASH_FLOW),
        (ForecastTarget.SAVINGS_AMOUNT, AnalyticsMetricCode.SAVINGS_AMOUNT),
    ],
)
def test_targets_inherit_phase_8_cash_flow_semantics(
    target: ForecastTarget, metric: AnalyticsMetricCode
) -> None:
    definition = forecast_target_definition(target)
    assert definition.source_metric is metric
    assert definition.statuses == frozenset({TransactionStatus.POSTED})
    assert definition.transaction_types <= frozenset(
        {TransactionType.INCOME, TransactionType.EXPENSE}
    )
    assert definition.unit == "money"


@pytest.mark.parametrize("value", ["INR", "inr", " usd "])
def test_currency_normalization_is_exact_and_conversion_free(value: str) -> None:
    assert normalize_forecast_currency(value) == value.strip().upper()


@pytest.mark.parametrize("value", ["", "IN", "RUPEE", "I1R", "₹₹₹", "İNR"])
def test_invalid_currency_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="forecast_invalid_currency"):
        normalize_forecast_currency(value)


@pytest.mark.parametrize(
    ("granularity", "maximum"),
    [
        (ForecastGranularity.DAY, MAX_DAILY_FORECAST_HORIZON),
        (ForecastGranularity.MONTH, MAX_MONTHLY_FORECAST_HORIZON),
    ],
)
def test_horizons_are_positive_and_bounded(
    granularity: ForecastGranularity, maximum: int
) -> None:
    assert validate_forecast_horizon(granularity=granularity, horizon=1) == 1
    assert validate_forecast_horizon(
        granularity=granularity, horizon=maximum
    ) == maximum
    for invalid in (0, maximum + 1, True):
        with pytest.raises(ValueError, match="forecast_unsupported_horizon"):
            validate_forecast_horizon(
                granularity=granularity, horizon=invalid  # type: ignore[arg-type]
            )


def test_forecasting_dependencies_are_pinned_and_prophet_is_optional() -> None:
    pyproject = (_REPOSITORY_ROOT / "backend" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '"anyio==4.14.0"' in pyproject
    for package in (
        '"pandas==3.0.5"',
        '"statsmodels==0.15.0"',
        '"xgboost-cpu==3.4.1"',
    ):
        assert package in pyproject
    assert "forecasting-prophet = [" in pyproject
    assert '"prophet==1.4.0"' in pyproject
