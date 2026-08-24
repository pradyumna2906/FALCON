"""Phase 8 closure policy, query budget, and freshness contracts."""

import pytest

from falcon_api.analytics.operations import (
    ANALYTICS_CLOSURE_VERSION,
    ANALYTICS_QUERY_BUDGETS,
    ANALYTICS_SNAPSHOT_POLICY,
    AnalyticsInvalidationMode,
    AnalyticsOperation,
    AnalyticsSnapshotMode,
    analytics_query_budget,
)
from falcon_api.analytics.semantics import ANALYTICS_CONTRACT_VERSION


def test_every_analytics_operation_has_one_fixed_query_budget() -> None:
    assert set(ANALYTICS_QUERY_BUDGETS) == set(AnalyticsOperation)
    assert {
        operation.value: analytics_query_budget(operation).max_statements
        for operation in AnalyticsOperation
    } == {
        "cash_flow": 3,
        "spending": 5,
        "recurring": 2,
        "spending_signals": 2,
        "budget": 3,
        "health_score": 5,
        "insights": 6,
        "dashboard_export": 5,
    }

    with pytest.raises(TypeError):
        ANALYTICS_QUERY_BUDGETS[AnalyticsOperation.CASH_FLOW] = (  # type: ignore[index]
            analytics_query_budget(AnalyticsOperation.CASH_FLOW)
        )


def test_snapshot_policy_selects_live_read_after_commit_freshness() -> None:
    policy = ANALYTICS_SNAPSHOT_POLICY

    assert policy.version == ANALYTICS_CLOSURE_VERSION == "2026.1"
    assert policy.contract_version == ANALYTICS_CONTRACT_VERSION
    assert policy.mode is AnalyticsSnapshotMode.LIVE
    assert policy.invalidation is AnalyticsInvalidationMode.READ_AFTER_COMMIT
    assert policy.persistent_snapshots is False
    assert policy.process_cache is False
    assert policy.cache_ttl_seconds is None
    assert policy.source_freshness_fields == (
        "transactions.updated_at",
        "financial_profiles.updated_at",
        "accounts.updated_at",
        "liability_details.updated_at",
        "budgets.updated_at",
        "budget_limits.updated_at",
    )
