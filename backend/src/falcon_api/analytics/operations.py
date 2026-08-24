"""Closed operational policy for Phase 8 analytics surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from falcon_api.analytics.semantics import ANALYTICS_CONTRACT_VERSION

ANALYTICS_CLOSURE_VERSION = "2026.1"
ANALYTICS_DASHBOARD_PERFORMANCE_BUDGET_SECONDS = 2.0
MAX_ANALYTICS_MONITORED_ITEMS = 1_000


class AnalyticsOperation(StrEnum):
    """Stable low-cardinality names for public analytics operations."""

    CASH_FLOW = "cash_flow"
    SPENDING = "spending"
    RECURRING = "recurring"
    SPENDING_SIGNALS = "spending_signals"
    BUDGET = "budget"
    HEALTH_SCORE = "health_score"
    INSIGHTS = "insights"
    DASHBOARD_EXPORT = "dashboard_export"


class AnalyticsSnapshotMode(StrEnum):
    """Snapshot mode selected after maximum-range validation."""

    LIVE = "live"


class AnalyticsInvalidationMode(StrEnum):
    """How committed source changes become visible to analytics."""

    READ_AFTER_COMMIT = "read_after_commit"


@dataclass(frozen=True, slots=True)
class AnalyticsQueryBudget:
    """Maximum SQL statements issued by one application operation."""

    operation: AnalyticsOperation
    max_statements: int


@dataclass(frozen=True, slots=True)
class AnalyticsSnapshotPolicy:
    """Explicit live-only policy that avoids unsafe premature caching."""

    version: str
    contract_version: str
    mode: AnalyticsSnapshotMode
    invalidation: AnalyticsInvalidationMode
    persistent_snapshots: bool
    process_cache: bool
    cache_ttl_seconds: int | None
    source_freshness_fields: tuple[str, ...]


_QUERY_BUDGETS = {
    AnalyticsOperation.CASH_FLOW: AnalyticsQueryBudget(
        AnalyticsOperation.CASH_FLOW,
        3,
    ),
    AnalyticsOperation.SPENDING: AnalyticsQueryBudget(
        AnalyticsOperation.SPENDING,
        5,
    ),
    AnalyticsOperation.RECURRING: AnalyticsQueryBudget(
        AnalyticsOperation.RECURRING,
        2,
    ),
    AnalyticsOperation.SPENDING_SIGNALS: AnalyticsQueryBudget(
        AnalyticsOperation.SPENDING_SIGNALS,
        2,
    ),
    AnalyticsOperation.BUDGET: AnalyticsQueryBudget(
        AnalyticsOperation.BUDGET,
        3,
    ),
    AnalyticsOperation.HEALTH_SCORE: AnalyticsQueryBudget(
        AnalyticsOperation.HEALTH_SCORE,
        5,
    ),
    AnalyticsOperation.INSIGHTS: AnalyticsQueryBudget(
        AnalyticsOperation.INSIGHTS,
        6,
    ),
    AnalyticsOperation.DASHBOARD_EXPORT: AnalyticsQueryBudget(
        AnalyticsOperation.DASHBOARD_EXPORT,
        5,
    ),
}

ANALYTICS_QUERY_BUDGETS = MappingProxyType(_QUERY_BUDGETS)
ANALYTICS_SNAPSHOT_POLICY = AnalyticsSnapshotPolicy(
    version=ANALYTICS_CLOSURE_VERSION,
    contract_version=ANALYTICS_CONTRACT_VERSION,
    mode=AnalyticsSnapshotMode.LIVE,
    invalidation=AnalyticsInvalidationMode.READ_AFTER_COMMIT,
    persistent_snapshots=False,
    process_cache=False,
    cache_ttl_seconds=None,
    source_freshness_fields=(
        "transactions.updated_at",
        "financial_profiles.updated_at",
        "accounts.updated_at",
        "liability_details.updated_at",
        "budgets.updated_at",
        "budget_limits.updated_at",
    ),
)


def analytics_query_budget(operation: AnalyticsOperation) -> AnalyticsQueryBudget:
    """Return the immutable SQL budget for one closed operation."""
    return ANALYTICS_QUERY_BUDGETS[operation]
