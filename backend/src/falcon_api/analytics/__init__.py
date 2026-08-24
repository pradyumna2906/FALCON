"""Versioned financial-analytics contracts and metric semantics."""

from falcon_api.analytics.periods import (
    AnalyticsPeriod,
    previous_period,
    resolve_analytics_period,
)
from falcon_api.analytics.recurring import (
    RECURRING_POLICY_VERSION,
    RecurringCadence,
    RecurringConfidenceBand,
    RecurringDecision,
    RecurringPattern,
    RecurringPatternType,
    RecurringReasonCode,
    detect_recurring_patterns,
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
from falcon_api.analytics.repository import AnalyticsRepository
from falcon_api.analytics.types import (
    MAX_ANALYTICS_DIMENSION_ROWS,
    AccountAggregate,
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
    CashFlowBucketAggregate,
    CategoryAggregate,
    MerchantAggregate,
    RecurringTransactionRecord,
)

__all__ = (
    "ANALYTICS_CONTRACT_VERSION",
    "MAX_ANALYTICS_RANGE_DAYS",
    "MAX_ANALYTICS_DIMENSION_ROWS",
    "RECURRING_POLICY_VERSION",
    "AccountAggregate",
    "AnalyticsCategoryState",
    "AnalyticsComparisonMode",
    "AnalyticsConfidenceLevel",
    "AnalyticsErrorCode",
    "AnalyticsMetricCode",
    "AnalyticsPeriod",
    "AnalyticsGranularity",
    "AnalyticsRepository",
    "AnalyticsSummaryAggregate",
    "CashFlowBucketAggregate",
    "CategoryAggregate",
    "MerchantAggregate",
    "MetricDefinition",
    "RecurringCadence",
    "RecurringConfidenceBand",
    "RecurringDecision",
    "RecurringPattern",
    "RecurringPatternType",
    "RecurringReasonCode",
    "RecurringTransactionRecord",
    "classification_completeness",
    "detect_recurring_patterns",
    "metric_definition",
    "previous_period",
    "resolve_analytics_period",
)
