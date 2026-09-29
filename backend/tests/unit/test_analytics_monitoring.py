"""Privacy and query-budget tests for analytics monitoring."""

import json
import logging

import pytest

from falcon_api.analytics.monitoring import (
    AnalyticsMonitor,
    AnalyticsResultState,
)
from falcon_api.analytics.operations import AnalyticsOperation
from falcon_api.core.logging import JsonLogFormatter


def test_analytics_monitor_emits_only_bounded_aggregate_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    times = iter((10.0, 10.125))
    logger = logging.getLogger("test.analytics.monitor")
    monitor = AnalyticsMonitor(logger=logger, timer=lambda: next(times))

    with caplog.at_level(logging.INFO, logger=logger.name):
        started_at = monitor.start()
        monitor.record_operation(
            AnalyticsOperation.DASHBOARD_EXPORT,
            started_at=started_at,
            range_days=366,
            query_count=5,
            item_count=516,
            result_state=AnalyticsResultState.NON_EMPTY,
        )

    payload = json.loads(JsonLogFormatter().format(caplog.records[-1]))
    assert payload["event"] == "analytics_operation_completed"
    assert payload["analytics_operation"] == "dashboard_export"
    assert payload["analytics_policy_version"] == "2026.1"
    assert payload["analytics_snapshot_mode"] == "live"
    assert payload["analytics_range_band"] == "093_366"
    assert payload["analytics_query_count"] == 5
    assert payload["analytics_query_budget"] == 5
    assert payload["analytics_item_count"] == 516
    assert payload["analytics_item_count_capped"] is False
    assert payload["analytics_result_state"] == "non_empty"
    assert payload["duration_ms"] == 125.0
    rendered = json.dumps(payload)
    for forbidden in (
        "user_id",
        "transaction_id",
        "account_id",
        "budget_id",
        "merchant",
        "category",
        "currency",
        "amount",
        "date_from",
        "date_to",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("range_days", "query_count", "item_count", "message"),
    [
        (0, 1, 0, "range_days"),
        (367, 1, 0, "range_days"),
        (1, 0, 0, "query_count"),
        (1, 6, 0, "query_count"),
        (1, 1, -1, "item_count"),
    ],
)
def test_analytics_monitor_rejects_unbounded_observations(
    range_days: int,
    query_count: int,
    item_count: int,
    message: str,
) -> None:
    monitor = AnalyticsMonitor()

    with pytest.raises(ValueError, match=message):
        monitor.record_operation(
            AnalyticsOperation.DASHBOARD_EXPORT,
            started_at=monitor.start(),
            range_days=range_days,
            query_count=query_count,
            item_count=item_count,
            result_state=AnalyticsResultState.EMPTY,
        )


def test_analytics_monitor_enforces_result_state_consistency() -> None:
    monitor = AnalyticsMonitor()
    started_at = monitor.start()

    with pytest.raises(ValueError, match="empty analytics"):
        monitor.record_operation(
            AnalyticsOperation.CASH_FLOW,
            started_at=started_at,
            range_days=1,
            query_count=1,
            item_count=1,
            result_state=AnalyticsResultState.EMPTY,
        )
    with pytest.raises(ValueError, match="non-empty analytics"):
        monitor.record_operation(
            AnalyticsOperation.CASH_FLOW,
            started_at=started_at,
            range_days=1,
            query_count=1,
            item_count=0,
            result_state=AnalyticsResultState.NON_EMPTY,
        )


def test_analytics_monitor_caps_item_count_without_failing_the_operation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.analytics.monitor.cap")
    monitor = AnalyticsMonitor(logger=logger)

    with caplog.at_level(logging.INFO, logger=logger.name):
        monitor.record_operation(
            AnalyticsOperation.BUDGET,
            started_at=monitor.start(),
            range_days=31,
            query_count=3,
            item_count=1_001,
            result_state=AnalyticsResultState.NON_EMPTY,
        )

    payload = json.loads(JsonLogFormatter().format(caplog.records[-1]))
    assert payload["analytics_item_count"] == 1_000
    assert payload["analytics_item_count_capped"] is True
