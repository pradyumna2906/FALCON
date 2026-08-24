"""Versioned financial-analytics contracts and metric semantics."""

from falcon_api.analytics.periods import (
    AnalyticsPeriod,
    previous_period,
    resolve_analytics_period,
)
from falcon_api.analytics.semantics import (
    ANALYTICS_CONTRACT_VERSION,
    MAX_ANALYTICS_RANGE_DAYS,
    AnalyticsCategoryState,
    AnalyticsComparisonMode,
    AnalyticsConfidenceLevel,
    AnalyticsErrorCode,
    AnalyticsMetricCode,
    MetricDefinition,
    classification_completeness,
    metric_definition,
)

__all__ = (
    "ANALYTICS_CONTRACT_VERSION",
    "MAX_ANALYTICS_RANGE_DAYS",
    "AnalyticsCategoryState",
    "AnalyticsComparisonMode",
    "AnalyticsConfidenceLevel",
    "AnalyticsErrorCode",
    "AnalyticsMetricCode",
    "AnalyticsPeriod",
    "MetricDefinition",
    "classification_completeness",
    "metric_definition",
    "previous_period",
    "resolve_analytics_period",
)
