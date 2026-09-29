"""Privacy-safe aggregate operational monitoring for financial analytics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from time import perf_counter

from falcon_api.analytics.operations import (
    ANALYTICS_CLOSURE_VERSION,
    ANALYTICS_SNAPSHOT_POLICY,
    MAX_ANALYTICS_MONITORED_ITEMS,
    AnalyticsOperation,
    analytics_query_budget,
)
from falcon_api.analytics.semantics import MAX_ANALYTICS_RANGE_DAYS


class AnalyticsResultState(StrEnum):
    """Closed result states safe for aggregate operational telemetry."""

    NON_EMPTY = "non_empty"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


class AnalyticsMonitor:
    """Emit bounded timings and counts without owner or financial values."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._logger = logger or logging.getLogger("falcon_api.analytics")
        self._timer = timer

    def start(self) -> float:
        """Capture a monotonic operation start time."""
        return self._timer()

    def record_operation(
        self,
        operation: AnalyticsOperation,
        *,
        started_at: float,
        range_days: int,
        query_count: int,
        item_count: int,
        result_state: AnalyticsResultState,
    ) -> None:
        """Validate one observation against policy and emit aggregate fields."""
        if type(range_days) is not int or not (
            1 <= range_days <= MAX_ANALYTICS_RANGE_DAYS
        ):
            raise ValueError(
                "analytics range_days must be between one and "
                f"{MAX_ANALYTICS_RANGE_DAYS}."
            )
        budget = analytics_query_budget(operation)
        if type(query_count) is not int or not (
            1 <= query_count <= budget.max_statements
        ):
            raise ValueError(
                f"analytics query_count exceeds the {operation.value} query budget."
            )
        if type(item_count) is not int or item_count < 0:
            raise ValueError("analytics item_count must be a non-negative integer.")
        if result_state is AnalyticsResultState.EMPTY and item_count != 0:
            raise ValueError("empty analytics observations cannot contain items.")
        if result_state is AnalyticsResultState.NON_EMPTY and item_count == 0:
            raise ValueError("non-empty analytics observations require an item.")

        duration_ms = max(0.0, (self._timer() - started_at) * 1000)
        monitored_item_count = min(item_count, MAX_ANALYTICS_MONITORED_ITEMS)
        self._logger.info(
            "analytics_operation_completed",
            extra={
                "analytics_operation": operation.value,
                "analytics_policy_version": ANALYTICS_CLOSURE_VERSION,
                "analytics_snapshot_mode": ANALYTICS_SNAPSHOT_POLICY.mode.value,
                "analytics_range_band": _range_band(range_days),
                "analytics_query_count": query_count,
                "analytics_query_budget": budget.max_statements,
                "analytics_item_count": monitored_item_count,
                "analytics_item_count_capped": monitored_item_count != item_count,
                "analytics_result_state": result_state.value,
                "duration_ms": round(duration_ms, 3),
            },
        )


def _range_band(day_count: int) -> str:
    if day_count <= 31:
        return "01_31"
    if day_count <= 92:
        return "032_092"
    return "093_366"
