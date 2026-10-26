"""Deterministic insight prioritization policy coverage."""

from datetime import date
from decimal import Decimal

from falcon_api.analytics.health_score import (
    FinancialHealthAnalysis,
    FinancialHealthFactor,
    FinancialHealthFactorResult,
    FinancialHealthFactorStatus,
    FinancialHealthReasonCode,
    FinancialHealthScoreStatus,
)
from falcon_api.analytics.insights import (
    InsightAnalysisStatus,
    InsightImpactBasis,
    InsightLifecycleState,
    InsightSeverity,
    InsightType,
    prioritize_insights,
)
from falcon_api.analytics.spending_signals import (
    SpendingSignal,
    SpendingSignalFamily,
    SpendingSignalReasonCode,
    SpendingSignalSeverity,
    SpendingSignalType,
)
from falcon_api.analytics.types import AnalyticsSummaryAggregate


def _summary(
    *,
    income: str = "40000",
    expense: str = "28000",
    eligible: int = 40,
    categorized: int = 38,
) -> AnalyticsSummaryAggregate:
    return AnalyticsSummaryAggregate(
        gross_income=Decimal(income),
        total_expense=Decimal(expense),
        internal_transfer_volume=Decimal("0"),
        net_adjustment=Decimal("0"),
        eligible_transaction_count=eligible,
        categorized_transaction_count=categorized,
        suggested_transaction_count=max(0, eligible - categorized),
        abstained_transaction_count=0,
        pending_count=0,
        transfer_entry_count=0,
        adjustment_count=0,
        other_currency_count=0,
        latest_transaction_date=date(2026, 8, 24) if eligible else None,
        source_last_updated_at=None,
    )


def _factor(
    factor: FinancialHealthFactor,
    *,
    score: str = "100",
    status: FinancialHealthFactorStatus = FinancialHealthFactorStatus.AVAILABLE,
) -> FinancialHealthFactorResult:
    available = status is FinancialHealthFactorStatus.AVAILABLE
    return FinancialHealthFactorResult(
        factor=factor,
        configured_weight=Decimal("10"),
        status=status,
        factor_score=Decimal(score) if available else None,
        observed_value=Decimal("0.5") if available else None,
        benchmark_value=Decimal("1") if available else None,
        effective_weight=Decimal("10") if available else Decimal("0"),
        contribution_points=Decimal("10") if available else Decimal("0"),
        reason_codes=(FinancialHealthReasonCode.DATA_COMPLETE,),
        explanation=f"{factor.value} evidence explanation.",
    )


def _health(
    overrides: dict[FinancialHealthFactor, tuple[str, FinancialHealthFactorStatus]]
    | None = None,
) -> FinancialHealthAnalysis:
    overrides = overrides or {}
    factors = tuple(
        _factor(
            factor,
            score=overrides.get(
                factor,
                ("100", FinancialHealthFactorStatus.AVAILABLE),
            )[0],
            status=overrides.get(
                factor,
                ("100", FinancialHealthFactorStatus.AVAILABLE),
            )[1],
        )
        for factor in FinancialHealthFactor
    )
    return FinancialHealthAnalysis(
        status=FinancialHealthScoreStatus.COMPLETE,
        score=Decimal("100"),
        available_weight=Decimal("100.00"),
        factors=factors,
        explanation="Complete evidence.",
    )


def _signal(
    signal_type: SpendingSignalType,
    *,
    merchant: str = "merchant",
    severity: SpendingSignalSeverity = SpendingSignalSeverity.MEDIUM,
    confidence: str = "0.8",
) -> SpendingSignal:
    return SpendingSignal(
        signal_type=signal_type,
        family=SpendingSignalFamily.POTENTIAL_LEAK,
        severity=severity,
        evidence_score=Decimal(confidence),
        reason_codes=(SpendingSignalReasonCode.REPEATED_FREQUENCY,),
        observed_amount=Decimal("500"),
        baseline_amount=Decimal("300"),
        excess_amount=Decimal("200"),
        share_of_total_expense=Decimal("0.1"),
        occurrence_count=5,
        first_observed_date=date(2026, 8, 1),
        last_observed_date=date(2026, 8, 20),
        normalized_merchant=merchant,
        display_name=merchant.title(),
        classification_code="general_shopping",
        category_name="General Shopping",
        explanation="Deterministic source evidence.",
    )


def test_negative_cash_flow_is_the_highest_priority_action() -> None:
    analysis = prioritize_insights(
        summary=_summary(income="20000", expense="25000"),
        health=_health(
            {
                FinancialHealthFactor.SAVINGS_RATE: (
                    "0",
                    FinancialHealthFactorStatus.AVAILABLE,
                )
            }
        ),
        spending_signals=(
            _signal(SpendingSignalType.REPEATED_SMALL_EXPENSES),
        ),
    )

    assert analysis.status is InsightAnalysisStatus.AVAILABLE
    assert analysis.insights[0].insight_type is InsightType.RESTORE_POSITIVE_CASH_FLOW
    assert analysis.insights[0].severity is InsightSeverity.HIGH
    assert analysis.insights[0].estimated_period_impact == Decimal("5000.0000")
    assert analysis.insights[0].impact_basis is InsightImpactBasis.CASH_FLOW_DEFICIT
    assert all(
        item.insight_type is not InsightType.IMPROVE_SAVINGS_RATE
        for item in analysis.insights
    )
    assert tuple(item.priority_score for item in analysis.insights) == tuple(
        sorted(
            (item.priority_score for item in analysis.insights),
            reverse=True,
        )
    )


def test_low_available_health_factors_create_bounded_actions() -> None:
    analysis = prioritize_insights(
        summary=_summary(),
        health=_health(
            {
                FinancialHealthFactor.EMERGENCY_FUND: (
                    "25",
                    FinancialHealthFactorStatus.AVAILABLE,
                ),
                FinancialHealthFactor.DEBT_BURDEN: (
                    "50",
                    FinancialHealthFactorStatus.AVAILABLE,
                ),
                FinancialHealthFactor.BUDGET_ADHERENCE: (
                    "0",
                    FinancialHealthFactorStatus.UNAVAILABLE,
                ),
                FinancialHealthFactor.DATA_COMPLETENESS: (
                    "80",
                    FinancialHealthFactorStatus.AVAILABLE,
                ),
            }
        ),
        spending_signals=(),
    )

    types = {item.insight_type for item in analysis.insights}
    assert types == {
        InsightType.BUILD_EMERGENCY_RESERVE,
        InsightType.REDUCE_DEBT_BURDEN,
        InsightType.IMPROVE_DATA_COMPLETENESS,
    }
    assert InsightType.PROTECT_BUDGET not in types
    assert all(
        item.lifecycle_state is InsightLifecycleState.ACTIVE
        for item in analysis.insights
    )
    assert all(
        "investment" not in item.recommended_action.lower()
        for item in analysis.insights
    )


def test_every_spending_signal_maps_to_a_reviewable_recommendation() -> None:
    signals = tuple(
        _signal(signal_type, merchant=f"merchant-{index}")
        for index, signal_type in enumerate(SpendingSignalType)
    )

    analysis = prioritize_insights(
        summary=_summary(),
        health=_health(),
        spending_signals=signals,
    )

    assert len(analysis.insights) == len(SpendingSignalType)
    assert all(
        item.estimated_period_impact == Decimal("200.0000")
        for item in analysis.insights
    )
    assert all(
        item.impact_basis is InsightImpactBasis.ESTIMATED_EXCESS_AMOUNT
        for item in analysis.insights
    )
    assert all(len(item.insight_id) == 24 for item in analysis.insights)


def test_duplicate_signal_dimensions_are_deduplicated_deterministically() -> None:
    lower = _signal(
        SpendingSignalType.RECURRING_SUBSCRIPTION,
        confidence="0.5",
    )
    higher = _signal(
        SpendingSignalType.RECURRING_SUBSCRIPTION,
        severity=SpendingSignalSeverity.HIGH,
        confidence="1",
    )

    first = prioritize_insights(
        summary=_summary(),
        health=_health(),
        spending_signals=(lower, higher),
    )
    second = prioritize_insights(
        summary=_summary(),
        health=_health(),
        spending_signals=(higher, lower),
    )

    assert first.candidate_count == 2
    assert len(first.insights) == 1
    assert first.insights == second.insights
    assert first.insights[0].severity is InsightSeverity.HIGH


def test_no_data_and_no_threshold_results_are_explicit() -> None:
    unavailable = prioritize_insights(
        summary=_summary(income="0", expense="0", eligible=0, categorized=0),
        health=_health(),
        spending_signals=(),
    )
    clear = prioritize_insights(
        summary=_summary(),
        health=_health(),
        spending_signals=(),
    )

    assert unavailable.status is InsightAnalysisStatus.INSUFFICIENT_DATA
    assert unavailable.insights == ()
    assert clear.status is InsightAnalysisStatus.NO_INSIGHTS
    assert clear.insights == ()


def test_unavailable_health_score_does_not_create_factor_recommendations() -> None:
    health = _health(
        {
            FinancialHealthFactor.EMERGENCY_FUND: (
                "0",
                FinancialHealthFactorStatus.AVAILABLE,
            )
        }
    )
    health = FinancialHealthAnalysis(
        status=FinancialHealthScoreStatus.UNAVAILABLE,
        score=None,
        available_weight=health.available_weight,
        factors=health.factors,
        explanation="The sample is too small for health recommendations.",
    )

    analysis = prioritize_insights(
        summary=_summary(eligible=5, categorized=5),
        health=health,
        spending_signals=(),
    )

    assert analysis.status is InsightAnalysisStatus.NO_INSIGHTS
    assert analysis.insights == ()
