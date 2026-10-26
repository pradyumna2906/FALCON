"""Deterministic prioritization of explainable personal-finance insights."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from hashlib import sha256

from falcon_api.analytics.health_score import (
    FinancialHealthAnalysis,
    FinancialHealthFactor,
    FinancialHealthFactorStatus,
    FinancialHealthScoreStatus,
)
from falcon_api.analytics.spending_signals import (
    SpendingSignal,
    SpendingSignalType,
)
from falcon_api.analytics.types import AnalyticsSummaryAggregate, money

INSIGHT_POLICY_VERSION = "2026.1"
MAX_INSIGHTS = 50
_RATE_QUANTUM = Decimal("0.000001")


class InsightAnalysisStatus(StrEnum):
    """Whether insight evidence exists and produced an active item."""

    AVAILABLE = "available"
    NO_INSIGHTS = "no_insights"
    INSUFFICIENT_DATA = "insufficient_data"


class InsightType(StrEnum):
    """Stable recommendation identities supported by policy 2026.1."""

    RESTORE_POSITIVE_CASH_FLOW = "restore_positive_cash_flow"
    IMPROVE_SAVINGS_RATE = "improve_savings_rate"
    BUILD_EMERGENCY_RESERVE = "build_emergency_reserve"
    REDUCE_DEBT_BURDEN = "reduce_debt_burden"
    PROTECT_BUDGET = "protect_budget"
    STABILIZE_CASH_FLOW = "stabilize_cash_flow"
    IMPROVE_DATA_COMPLETENESS = "improve_data_completeness"
    REVIEW_BANK_CHARGES = "review_bank_charges"
    REVIEW_SMALL_EXPENSES = "review_small_expenses"
    REVIEW_SUBSCRIPTION = "review_subscription"
    REVIEW_MERCHANT_CONCENTRATION = "review_merchant_concentration"
    REVIEW_CATEGORY_SPIKE = "review_category_spike"
    VERIFY_UNUSUAL_AMOUNT = "verify_unusual_amount"
    REVIEW_DISCRETIONARY_SPIKE = "review_discretionary_spike"
    VERIFY_DUPLICATE_LIKE_EXPENSE = "verify_duplicate_like_expense"


class InsightCategory(StrEnum):
    """Dashboard groups that do not imply regulated financial advice."""

    CASH_FLOW = "cash_flow"
    RESILIENCE = "resilience"
    DEBT = "debt"
    BUDGET = "budget"
    SPENDING = "spending"
    DATA_QUALITY = "data_quality"


class InsightSeverity(StrEnum):
    """Potential personal-finance impact, not transaction fraud severity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InsightUrgency(StrEnum):
    """Suggested review timing without alarms or guarantees."""

    ROUTINE = "routine"
    SOON = "soon"
    IMMEDIATE = "immediate"


class InsightConfidence(StrEnum):
    """Deterministic evidence bands for one recommendation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InsightLifecycleState(StrEnum):
    """Live policy items are active; persistence is intentionally deferred."""

    ACTIVE = "active"


class InsightImpactBasis(StrEnum):
    """Meaning of a monetary impact estimate."""

    OBSERVED_REVIEWABLE_AMOUNT = "observed_reviewable_amount"
    ESTIMATED_EXCESS_AMOUNT = "estimated_excess_amount"
    CASH_FLOW_DEFICIT = "cash_flow_deficit"


class InsightReasonCode(StrEnum):
    """Bounded reasons for recommendation creation and prioritization."""

    NEGATIVE_NET_CASH_FLOW = "negative_net_cash_flow"
    LOW_FACTOR_SCORE = "low_factor_score"
    HEALTH_FACTOR_EVIDENCE = "health_factor_evidence"
    SPENDING_SIGNAL_EVIDENCE = "spending_signal_evidence"
    HIGH_SIGNAL_SEVERITY = "high_signal_severity"
    MEASURABLE_PERIOD_IMPACT = "measurable_period_impact"
    CLASSIFICATION_GAP = "classification_gap"


@dataclass(frozen=True, slots=True)
class PersonalFinanceInsight:
    """One bounded, deduplicated, explainable recommendation."""

    insight_id: str
    insight_type: InsightType
    category: InsightCategory
    severity: InsightSeverity
    urgency: InsightUrgency
    confidence: InsightConfidence
    confidence_score: Decimal
    priority_score: Decimal
    lifecycle_state: InsightLifecycleState
    reason_codes: tuple[InsightReasonCode, ...]
    title: str
    explanation: str
    recommended_action: str
    estimated_period_impact: Decimal | None
    impact_basis: InsightImpactBasis | None
    normalized_merchant: str | None
    display_name: str | None
    classification_code: str | None
    category_name: str | None


@dataclass(frozen=True, slots=True)
class InsightAnalysis:
    """Complete live policy result before the public response limit."""

    status: InsightAnalysisStatus
    candidate_count: int
    insights: tuple[PersonalFinanceInsight, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class _InsightTemplate:
    insight_type: InsightType
    category: InsightCategory
    title: str
    action: str


_SIGNAL_TEMPLATES = {
    SpendingSignalType.BANK_CHARGE_LEAKAGE: _InsightTemplate(
        InsightType.REVIEW_BANK_CHARGES,
        InsightCategory.SPENDING,
        "Review repeated bank charges",
        (
            "Check the listed charges and account fee rules; dispute only an "
            "incorrect charge."
        ),
    ),
    SpendingSignalType.REPEATED_SMALL_EXPENSES: _InsightTemplate(
        InsightType.REVIEW_SMALL_EXPENSES,
        InsightCategory.SPENDING,
        "Review repeated small expenses",
        "Group these payments into a weekly cap and decide which ones still add value.",
    ),
    SpendingSignalType.RECURRING_SUBSCRIPTION: _InsightTemplate(
        InsightType.REVIEW_SUBSCRIPTION,
        InsightCategory.SPENDING,
        "Review a recurring subscription",
        "Confirm that the subscription is still used before changing or cancelling it.",
    ),
    SpendingSignalType.MERCHANT_CONCENTRATION: _InsightTemplate(
        InsightType.REVIEW_MERCHANT_CONCENTRATION,
        InsightCategory.SPENDING,
        "Review concentrated merchant spending",
        (
            "Review whether this merchant's share fits your priorities for the "
            "selected period."
        ),
    ),
    SpendingSignalType.CATEGORY_SPIKE: _InsightTemplate(
        InsightType.REVIEW_CATEGORY_SPIKE,
        InsightCategory.SPENDING,
        "Review a category spending spike",
        (
            "Compare the recent category activity with your needs and set a "
            "short-term limit if useful."
        ),
    ),
    SpendingSignalType.UNUSUAL_AMOUNT: _InsightTemplate(
        InsightType.VERIFY_UNUSUAL_AMOUNT,
        InsightCategory.SPENDING,
        "Verify an unusual expense amount",
        (
            "Confirm that the expense is expected and correctly recorded before "
            "taking action."
        ),
    ),
    SpendingSignalType.DISCRETIONARY_SPIKE: _InsightTemplate(
        InsightType.REVIEW_DISCRETIONARY_SPIKE,
        InsightCategory.SPENDING,
        "Review a discretionary spending spike",
        (
            "Pause non-essential spending in this area until it returns to your "
            "normal range."
        ),
    ),
    SpendingSignalType.DUPLICATE_LIKE_EXPENSE: _InsightTemplate(
        InsightType.VERIFY_DUPLICATE_LIKE_EXPENSE,
        InsightCategory.SPENDING,
        "Verify a duplicate-like expense",
        (
            "Check the source statement before treating either entry as an "
            "actual duplicate."
        ),
    ),
}


def prioritize_insights(
    *,
    summary: AnalyticsSummaryAggregate,
    health: FinancialHealthAnalysis,
    spending_signals: tuple[SpendingSignal, ...],
) -> InsightAnalysis:
    """Convert existing evidence into cautious, deterministic next actions."""
    if summary.eligible_transaction_count == 0:
        return InsightAnalysis(
            status=InsightAnalysisStatus.INSUFFICIENT_DATA,
            candidate_count=0,
            insights=(),
            explanation=(
                "No eligible posted transactions were available to produce insights."
            ),
        )

    candidates: list[PersonalFinanceInsight] = []
    if summary.net_cash_flow < 0:
        candidates.append(_cash_flow_insight(summary))

    candidates.extend(
        _health_insights(
            health,
            suppress_savings=summary.net_cash_flow < 0,
        )
    )
    candidates.extend(_signal_insight(signal) for signal in spending_signals)

    deduplicated: dict[str, PersonalFinanceInsight] = {}
    for candidate in candidates:
        current = deduplicated.get(candidate.insight_id)
        if current is None or _sort_key(candidate) < _sort_key(current):
            deduplicated[candidate.insight_id] = candidate
    ordered = tuple(sorted(deduplicated.values(), key=_sort_key))
    if not ordered:
        return InsightAnalysis(
            status=InsightAnalysisStatus.NO_INSIGHTS,
            candidate_count=len(candidates),
            insights=(),
            explanation=(
                "The available evidence did not cross any recommendation threshold."
            ),
        )
    return InsightAnalysis(
        status=InsightAnalysisStatus.AVAILABLE,
        candidate_count=len(candidates),
        insights=ordered,
        explanation=(
            "Insights are ordered by fixed severity, urgency, confidence, and "
            "stable tie-break rules; they are guidance, not financial product advice."
        ),
    )


def _cash_flow_insight(
    summary: AnalyticsSummaryAggregate,
) -> PersonalFinanceInsight:
    deficit = money(-summary.net_cash_flow)
    return _build(
        insight_type=InsightType.RESTORE_POSITIVE_CASH_FLOW,
        category=InsightCategory.CASH_FLOW,
        severity=InsightSeverity.HIGH,
        urgency=InsightUrgency.IMMEDIATE,
        confidence_score=Decimal("1"),
        reason_codes=(
            InsightReasonCode.NEGATIVE_NET_CASH_FLOW,
            InsightReasonCode.MEASURABLE_PERIOD_IMPACT,
        ),
        title="Restore positive cash flow",
        explanation=(
            "Posted expenses exceeded posted income in the selected period by "
            f"{deficit:.4f}."
        ),
        action=(
            "Review the largest flexible expenses and protect essential payments "
            "before adding new commitments."
        ),
        estimated_period_impact=deficit,
        impact_basis=InsightImpactBasis.CASH_FLOW_DEFICIT,
    )


def _health_insights(
    health: FinancialHealthAnalysis,
    *,
    suppress_savings: bool,
) -> list[PersonalFinanceInsight]:
    if health.status is FinancialHealthScoreStatus.UNAVAILABLE:
        return []
    results = {item.factor: item for item in health.factors}
    definitions = (
        (
            FinancialHealthFactor.SAVINGS_RATE,
            InsightType.IMPROVE_SAVINGS_RATE,
            InsightCategory.CASH_FLOW,
            "Improve the savings rate",
            (
                "Choose one realistic expense reduction and direct the released "
                "cash to savings."
            ),
            Decimal("60"),
        ),
        (
            FinancialHealthFactor.EMERGENCY_FUND,
            InsightType.BUILD_EMERGENCY_RESERVE,
            InsightCategory.RESILIENCE,
            "Build emergency-fund readiness",
            (
                "Set a small recurring transfer toward the emergency-fund target "
                "before optional spending."
            ),
            Decimal("75"),
        ),
        (
            FinancialHealthFactor.DEBT_BURDEN,
            InsightType.REDUCE_DEBT_BURDEN,
            InsightCategory.DEBT,
            "Review debt-service burden",
            (
                "List required debt payments and prioritize avoiding missed or "
                "penalized payments."
            ),
            Decimal("75"),
        ),
        (
            FinancialHealthFactor.BUDGET_ADHERENCE,
            InsightType.PROTECT_BUDGET,
            InsightCategory.BUDGET,
            "Protect the selected budget",
            "Reduce flexible category spending for the rest of the budget period.",
            Decimal("80"),
        ),
        (
            FinancialHealthFactor.CASH_FLOW_STABILITY,
            InsightType.STABILIZE_CASH_FLOW,
            InsightCategory.CASH_FLOW,
            "Stabilize monthly cash flow",
            (
                "Keep a buffer for variable months and align flexible spending "
                "with lower-income periods."
            ),
            Decimal("75"),
        ),
        (
            FinancialHealthFactor.DATA_COMPLETENESS,
            InsightType.IMPROVE_DATA_COMPLETENESS,
            InsightCategory.DATA_QUALITY,
            "Improve analytics completeness",
            (
                "Review uncategorized and suggested transactions so future "
                "analytics use stronger evidence."
            ),
            Decimal("90"),
        ),
    )
    insights: list[PersonalFinanceInsight] = []
    for factor, insight_type, category, title, action, threshold in definitions:
        if suppress_savings and factor is FinancialHealthFactor.SAVINGS_RATE:
            continue
        result = results[factor]
        if (
            result.status is FinancialHealthFactorStatus.UNAVAILABLE
            or result.factor_score is None
            or result.factor_score >= threshold
        ):
            continue
        severity = (
            InsightSeverity.HIGH
            if result.factor_score < Decimal("30")
            else InsightSeverity.MEDIUM
            if result.factor_score < Decimal("60")
            else InsightSeverity.LOW
        )
        urgency = (
            InsightUrgency.IMMEDIATE
            if severity is InsightSeverity.HIGH
            and factor in {
                FinancialHealthFactor.DEBT_BURDEN,
                FinancialHealthFactor.BUDGET_ADHERENCE,
            }
            else InsightUrgency.SOON
            if severity is not InsightSeverity.LOW
            else InsightUrgency.ROUTINE
        )
        confidence_score = (
            Decimal("1")
            if health.available_weight == Decimal("100.00")
            else Decimal("0.75")
        )
        insights.append(
            _build(
                insight_type=insight_type,
                category=category,
                severity=severity,
                urgency=urgency,
                confidence_score=confidence_score,
                reason_codes=(
                    InsightReasonCode.LOW_FACTOR_SCORE,
                    InsightReasonCode.HEALTH_FACTOR_EVIDENCE,
                    *(
                        (InsightReasonCode.CLASSIFICATION_GAP,)
                        if factor is FinancialHealthFactor.DATA_COMPLETENESS
                        else ()
                    ),
                ),
                title=title,
                explanation=result.explanation,
                action=action,
                estimated_period_impact=None,
                impact_basis=None,
            )
        )
    return insights


def _signal_insight(signal: SpendingSignal) -> PersonalFinanceInsight:
    template = _SIGNAL_TEMPLATES[signal.signal_type]
    severity = InsightSeverity(signal.severity.value)
    urgency = (
        InsightUrgency.SOON
        if severity is InsightSeverity.HIGH
        else InsightUrgency.ROUTINE
    )
    impact = signal.excess_amount
    basis = (
        InsightImpactBasis.ESTIMATED_EXCESS_AMOUNT
        if impact is not None
        else InsightImpactBasis.OBSERVED_REVIEWABLE_AMOUNT
    )
    if impact is None:
        impact = signal.observed_amount
    reason_codes = [InsightReasonCode.SPENDING_SIGNAL_EVIDENCE]
    if severity is InsightSeverity.HIGH:
        reason_codes.append(InsightReasonCode.HIGH_SIGNAL_SEVERITY)
    if impact > 0:
        reason_codes.append(InsightReasonCode.MEASURABLE_PERIOD_IMPACT)
    return _build(
        insight_type=template.insight_type,
        category=template.category,
        severity=severity,
        urgency=urgency,
        confidence_score=signal.evidence_score,
        reason_codes=tuple(reason_codes),
        title=template.title,
        explanation=signal.explanation,
        action=template.action,
        estimated_period_impact=impact,
        impact_basis=basis,
        normalized_merchant=signal.normalized_merchant,
        display_name=signal.display_name,
        classification_code=signal.classification_code,
        category_name=signal.category_name,
    )


def _build(
    *,
    insight_type: InsightType,
    category: InsightCategory,
    severity: InsightSeverity,
    urgency: InsightUrgency,
    confidence_score: Decimal,
    reason_codes: tuple[InsightReasonCode, ...],
    title: str,
    explanation: str,
    action: str,
    estimated_period_impact: Decimal | None,
    impact_basis: InsightImpactBasis | None,
    normalized_merchant: str | None = None,
    display_name: str | None = None,
    classification_code: str | None = None,
    category_name: str | None = None,
) -> PersonalFinanceInsight:
    confidence_score = max(Decimal("0"), min(Decimal("1"), confidence_score)).quantize(
        _RATE_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
    confidence = (
        InsightConfidence.HIGH
        if confidence_score >= Decimal("0.800000")
        else InsightConfidence.MEDIUM
        if confidence_score >= Decimal("0.500000")
        else InsightConfidence.LOW
    )
    identity = "|".join(
        (
            INSIGHT_POLICY_VERSION,
            insight_type.value,
            normalized_merchant or "",
            classification_code or "",
        )
    )
    insight = PersonalFinanceInsight(
        insight_id=sha256(identity.encode("utf-8")).hexdigest()[:24],
        insight_type=insight_type,
        category=category,
        severity=severity,
        urgency=urgency,
        confidence=confidence,
        confidence_score=confidence_score,
        priority_score=Decimal("0"),
        lifecycle_state=InsightLifecycleState.ACTIVE,
        reason_codes=reason_codes,
        title=title,
        explanation=explanation,
        recommended_action=action,
        estimated_period_impact=(
            money(estimated_period_impact)
            if estimated_period_impact is not None
            else None
        ),
        impact_basis=impact_basis,
        normalized_merchant=normalized_merchant,
        display_name=display_name,
        classification_code=classification_code,
        category_name=category_name,
    )
    return replace(insight, priority_score=_priority_score(insight))


def _priority_score(insight: PersonalFinanceInsight) -> Decimal:
    severity_points = {
        InsightSeverity.LOW: Decimal("20"),
        InsightSeverity.MEDIUM: Decimal("40"),
        InsightSeverity.HIGH: Decimal("55"),
    }[insight.severity]
    urgency_points = {
        InsightUrgency.ROUTINE: Decimal("5"),
        InsightUrgency.SOON: Decimal("15"),
        InsightUrgency.IMMEDIATE: Decimal("25"),
    }[insight.urgency]
    confidence_points = insight.confidence_score * Decimal("20")
    return min(
        Decimal("100"),
        severity_points + urgency_points + confidence_points,
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_EVEN,
    )


def _sort_key(insight: PersonalFinanceInsight) -> tuple[Decimal, str]:
    return (-insight.priority_score, insight.insight_id)
