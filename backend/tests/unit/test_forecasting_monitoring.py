"""Tests for bounded privacy-safe forecasting telemetry."""

from unittest.mock import Mock

import pytest

from falcon_api.forecasting import (
    ForecastEligibility,
    ForecastGranularity,
    ForecastMonitor,
    ForecastTarget,
)
from falcon_api.forecasting.monitoring import _count_band


def test_monitor_emits_only_bounded_non_financial_fields() -> None:
    logger = Mock()
    ticks = iter((1.0, 1.125))
    monitor = ForecastMonitor(logger=logger, timer=lambda: next(ticks))
    started = monitor.start()
    monitor.record_generation(
        started_at=started,
        target=ForecastTarget.TOTAL_EXPENSE,
        granularity=ForecastGranularity.MONTH,
        history_periods=18,
        horizon=6,
        eligibility=ForecastEligibility.NORMAL,
        candidate_count=10,
        failure_count=2,
        selected_model_code="historical_mean",
    )
    event = logger.info.call_args.kwargs["extra"]
    assert event["forecast_history_band"] == "013_031"
    assert event["forecast_horizon_band"] == "004_012"
    assert event["duration_ms"] == 125.0
    assert not {"user_id", "currency", "expected_value"} & event.keys()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("history_periods", 0),
        ("horizon", True),
        ("candidate_count", 0),
        ("failure_count", 3),
        ("selected_model_code", " "),
    ),
)
def test_monitor_rejects_invalid_counts(field: str, value: int | str) -> None:
    monitor = ForecastMonitor(timer=lambda: 1.0)
    arguments = {
        "started_at": 1.0,
        "target": ForecastTarget.TOTAL_EXPENSE,
        "granularity": ForecastGranularity.MONTH,
        "history_periods": 3,
        "horizon": 1,
        "eligibility": ForecastEligibility.PROVISIONAL,
        "candidate_count": 2,
        "failure_count": 0,
        "selected_model_code": "last_value",
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        monitor.record_generation(**arguments)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (3, "001_003"),
        (12, "004_012"),
        (31, "013_031"),
        (92, "032_092"),
        (366, "093_366"),
        (367, "367_plus"),
    ),
)
def test_count_bands_are_stable(value: int, expected: str) -> None:
    assert _count_band(value) == expected


def test_monitor_floors_duration_and_caps_candidate_counts() -> None:
    logger = Mock()
    monitor = ForecastMonitor(logger=logger, timer=lambda: 0.5)
    monitor.record_generation(
        started_at=1.0,
        target=ForecastTarget.NET_CASH_FLOW,
        granularity=ForecastGranularity.DAY,
        history_periods=400,
        horizon=100,
        eligibility=ForecastEligibility.PROVISIONAL,
        candidate_count=20,
        failure_count=20,
        selected_model_code="xgboost_lagged_day",
    )
    event = logger.info.call_args.kwargs["extra"]
    assert event["duration_ms"] == 0.0
    assert event["forecast_candidate_count"] == 16
    assert event["forecast_failure_count"] == 16
