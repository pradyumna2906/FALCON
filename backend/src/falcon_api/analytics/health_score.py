"""Deterministic and explainable financial-health score policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from falcon_api.analytics.types import (
    AnalyticsSummaryAggregate,
    CashFlowBucketAggregate,
    CategoryAggregate,
    FinancialHealthProfileAggregate,
)
from falcon_api.models.enums import ProfileCompletionStatus

FINANCIAL_HEALTH_POLICY_VERSION = "2026.1"
MIN_HEALTH_ELIGIBLE_TRANSACTIONS = 10
MIN_HEALTH_AVAILABLE_WEIGHT = Decimal("50")
DEFAULT_EMERGENCY_TARGET_MONTHS = Decimal("3")
_DAYS_PER_MONTH = Decimal("30.4375")
_SCORE_QUANTUM = Decimal("0.01")
_RATIO_QUANTUM = Decimal("0.000001")
_ZERO = Decimal("0")
_ONE = Decimal("1")


class FinancialHealthScoreStatus(StrEnum):
    """Whether the composite is supported by complete or partial evidence."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class FinancialHealthFactor(StrEnum):
    """Stable factor identifiers in policy display order."""

    SAVINGS_RATE = "savings_rate"
    EMERGENCY_FUND = "emergency_fund_readiness"
    DEBT_BURDEN = "debt_service_burden"
    BUDGET_ADHERENCE = "budget_adherence"
    CASH_FLOW_STABILITY = "cash_flow_stability"
    SPENDING_CONCENTRATION = "spending_concentration"
    DATA_COMPLETENESS = "data_completeness"


class FinancialHealthFactorStatus(StrEnum):
    """Availability of one factor's evidence."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class FinancialHealthReasonCode(StrEnum):
    """Bounded reasons that explain factor ratings and abstentions."""

    STRONG_SAVINGS = "strong_savings"
    POSITIVE_SAVINGS = "positive_savings"
    NON_POSITIVE_SAVINGS = "non_positive_savings"
    INCOME_UNAVAILABLE = "income_unavailable"
    EMERGENCY_TARGET_MET = "emergency_target_met"
    EMERGENCY_FUND_GAP = "emergency_fund_gap"
    EXPENSE_BASELINE_UNAVAILABLE = "expense_baseline_unavailable"
    USER_EMERGENCY_TARGET = "user_emergency_target"
    DEFAULT_EMERGENCY_TARGET = "default_emergency_target"
    NO_DEBT_ACCOUNTS = "no_debt_accounts"
    DEBT_BURDEN_MEASURED = "debt_burden_measured"
    LIABILITY_TERMS_INCOMPLETE = "liability_terms_incomplete"
    BUDGET_WITHIN_LIMIT = "budget_within_limit"
    BUDGET_PRESSURE = "budget_pressure"
    BUDGET_NOT_SELECTED = "budget_not_selected"
    BUDGET_LIMIT_UNAVAILABLE = "budget_limit_unavailable"
    CASH_FLOW_STABLE = "cash_flow_stable"
    CASH_FLOW_VOLATILE = "cash_flow_volatile"
    CASH_FLOW_HISTORY_INSUFFICIENT = "cash_flow_history_insufficient"
    SPENDING_DIVERSIFIED = "spending_diversified"
    SPENDING_CONCENTRATED = "spending_concentrated"
    CATEGORY_EVIDENCE_INSUFFICIENT = "category_evidence_insufficient"
    DATA_COMPLETE = "data_complete"
    DATA_INCOMPLETE = "data_incomplete"


@dataclass(frozen=True, slots=True)
class BudgetHealthEvidence:
    """Optional already-owner-scoped budget evidence for the selected period."""

    limit_amount: Decimal | None
    observed_spending: Decimal
    pace_projected_spending: Decimal


@dataclass(frozen=True, slots=True)
class FinancialHealthFactorResult:
    """One transparent configured factor and its score contribution."""

    factor: FinancialHealthFactor
    configured_weight: Decimal
    status: FinancialHealthFactorStatus
    factor_score: Decimal | None
    observed_value: Decimal | None
    benchmark_value: Decimal | None
    effective_weight: Decimal
    contribution_points: Decimal
    reason_codes: tuple[FinancialHealthReasonCode, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class FinancialHealthAnalysis:
    """Composite score plus all factor-level provenance."""

    status: FinancialHealthScoreStatus
    score: Decimal | None
    available_weight: Decimal
    factors: tuple[FinancialHealthFactorResult, ...]
    explanation: str


_WEIGHTS = {
    FinancialHealthFactor.SAVINGS_RATE: Decimal("25"),
    FinancialHealthFactor.EMERGENCY_FUND: Decimal("20"),
    FinancialHealthFactor.DEBT_BURDEN: Decimal("15"),
    FinancialHealthFactor.BUDGET_ADHERENCE: Decimal("15"),
    FinancialHealthFactor.CASH_FLOW_STABILITY: Decimal("10"),
    FinancialHealthFactor.SPENDING_CONCENTRATION: Decimal("5"),
    FinancialHealthFactor.DATA_COMPLETENESS: Decimal("10"),
}


def evaluate_financial_health(
    *,
    summary: AnalyticsSummaryAggregate,
    cash_flow_buckets: tuple[CashFlowBucketAggregate, ...],
    expense_categories: tuple[CategoryAggregate, ...],
    profile: FinancialHealthProfileAggregate,
    period_date_from: date,
    period_date_to: date,
    budget: BudgetHealthEvidence | None,
) -> FinancialHealthAnalysis:
    """Apply policy 2026.1 using exact decimals and explicit abstention."""
    if period_date_to < period_date_from:
        raise ValueError("Health-score period dates must be ordered.")
    period_day_count = (period_date_to - period_date_from).days + 1

    factors = (
        _savings_factor(summary),
        _emergency_factor(summary, profile, period_day_count),
        _debt_factor(summary, profile, period_day_count),
        _budget_factor(budget),
        _stability_factor(
            cash_flow_buckets,
            period_date_from=period_date_from,
            period_date_to=period_date_to,
        ),
        _concentration_factor(expense_categories),
        _completeness_factor(summary, profile),
    )
    available_weight = sum(
        (
            item.configured_weight
            for item in factors
            if item.status is FinancialHealthFactorStatus.AVAILABLE
        ),
        _ZERO,
    )
    enough_evidence = (
        summary.eligible_transaction_count >= MIN_HEALTH_ELIGIBLE_TRANSACTIONS
        and available_weight >= MIN_HEALTH_AVAILABLE_WEIGHT
    )
    if not enough_evidence:
        return FinancialHealthAnalysis(
            status=FinancialHealthScoreStatus.UNAVAILABLE,
            score=None,
            available_weight=_score(available_weight),
            factors=factors,
            explanation=(
                "No composite score was produced because at least 10 eligible "
                "transactions and 50 configured weight points are required."
            ),
        )

    weighted = tuple(
        _apply_effective_weight(item, available_weight) for item in factors
    )
    composite = sum(
        (item.contribution_points for item in weighted),
        _ZERO,
    ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)
    status = (
        FinancialHealthScoreStatus.COMPLETE
        if available_weight == Decimal("100")
        else FinancialHealthScoreStatus.PARTIAL
    )
    return FinancialHealthAnalysis(
        status=status,
        score=composite,
        available_weight=_score(available_weight),
        factors=weighted,
        explanation=(
            "The score is a deterministic planning indicator; it is not a "
            "credit score, investment recommendation, or forecast."
        ),
    )


def _savings_factor(
    summary: AnalyticsSummaryAggregate,
) -> FinancialHealthFactorResult:
    rate = summary.savings_rate
    if rate is None:
        return _unavailable(
            FinancialHealthFactor.SAVINGS_RATE,
            FinancialHealthReasonCode.INCOME_UNAVAILABLE,
            "Savings rate is unavailable because observed gross income is zero.",
        )
    if rate <= 0:
        rating = _ZERO
        reason = FinancialHealthReasonCode.NON_POSITIVE_SAVINGS
    elif rate < Decimal("0.10"):
        rating = rate / Decimal("0.10") * Decimal("0.40")
        reason = FinancialHealthReasonCode.POSITIVE_SAVINGS
    elif rate < Decimal("0.20"):
        rating = Decimal("0.40") + (
            (rate - Decimal("0.10")) / Decimal("0.10") * Decimal("0.30")
        )
        reason = FinancialHealthReasonCode.POSITIVE_SAVINGS
    elif rate < Decimal("0.30"):
        rating = Decimal("0.70") + (
            (rate - Decimal("0.20")) / Decimal("0.10") * Decimal("0.30")
        )
        reason = FinancialHealthReasonCode.POSITIVE_SAVINGS
    else:
        rating = _ONE
        reason = FinancialHealthReasonCode.STRONG_SAVINGS
    return _available(
        FinancialHealthFactor.SAVINGS_RATE,
        rating=rating,
        observed=rate,
        benchmark=Decimal("0.30"),
        reasons=(reason,),
        explanation=(
            "Observed cash-flow savings rate is compared with the policy's "
            "30% full-score benchmark."
        ),
    )


def _emergency_factor(
    summary: AnalyticsSummaryAggregate,
    profile: FinancialHealthProfileAggregate,
    period_day_count: int,
) -> FinancialHealthFactorResult:
    if summary.total_expense <= 0:
        return _unavailable(
            FinancialHealthFactor.EMERGENCY_FUND,
            FinancialHealthReasonCode.EXPENSE_BASELINE_UNAVAILABLE,
            "Emergency readiness needs positive observed expense evidence.",
        )
    target = profile.emergency_fund_target_months
    if target is not None and target > 0:
        target_reason = FinancialHealthReasonCode.USER_EMERGENCY_TARGET
    else:
        target = DEFAULT_EMERGENCY_TARGET_MONTHS
        target_reason = FinancialHealthReasonCode.DEFAULT_EMERGENCY_TARGET
    monthly_expense = (
        summary.total_expense / Decimal(period_day_count) * _DAYS_PER_MONTH
    )
    months_covered = max(_ZERO, profile.liquid_balance) / monthly_expense
    rating = _clamp(months_covered / target)
    gap_reason = (
        FinancialHealthReasonCode.EMERGENCY_TARGET_MET
        if rating == _ONE
        else FinancialHealthReasonCode.EMERGENCY_FUND_GAP
    )
    return _available(
        FinancialHealthFactor.EMERGENCY_FUND,
        rating=rating,
        observed=months_covered,
        benchmark=target,
        reasons=(gap_reason, target_reason),
        explanation=(
            "Positive active bank, cash, and wallet balances are divided by "
            "the selected period's monthly-equivalent expense baseline."
        ),
    )


def _debt_factor(
    summary: AnalyticsSummaryAggregate,
    profile: FinancialHealthProfileAggregate,
    period_day_count: int,
) -> FinancialHealthFactorResult:
    if profile.liability_account_count == 0:
        return _available(
            FinancialHealthFactor.DEBT_BURDEN,
            rating=_ONE,
            observed=_ZERO,
            benchmark=Decimal("0.30"),
            reasons=(FinancialHealthReasonCode.NO_DEBT_ACCOUNTS,),
            explanation="No active loan or credit-card account was found.",
        )
    if profile.liability_payment_count != profile.liability_account_count:
        return _unavailable(
            FinancialHealthFactor.DEBT_BURDEN,
            FinancialHealthReasonCode.LIABILITY_TERMS_INCOMPLETE,
            "Every active debt account needs a minimum-payment value.",
        )
    monthly_income = summary.gross_income / Decimal(period_day_count) * _DAYS_PER_MONTH
    if monthly_income <= 0:
        burden = _ONE
        rating = _ZERO
    else:
        burden = profile.monthly_debt_payment / monthly_income
        rating = _debt_rating(burden)
    return _available(
        FinancialHealthFactor.DEBT_BURDEN,
        rating=rating,
        observed=burden,
        benchmark=Decimal("0.30"),
        reasons=(FinancialHealthReasonCode.DEBT_BURDEN_MEASURED,),
        explanation=(
            "Stored monthly minimum payments are divided by the period's "
            "monthly-equivalent gross income."
        ),
    )


def _budget_factor(
    budget: BudgetHealthEvidence | None,
) -> FinancialHealthFactorResult:
    if budget is None:
        return _unavailable(
            FinancialHealthFactor.BUDGET_ADHERENCE,
            FinancialHealthReasonCode.BUDGET_NOT_SELECTED,
            "Budget adherence is unavailable because no aligned budget was selected.",
        )
    if budget.limit_amount is None:
        return _unavailable(
            FinancialHealthFactor.BUDGET_ADHERENCE,
            FinancialHealthReasonCode.BUDGET_LIMIT_UNAVAILABLE,
            "The selected aligned budget has no overall spending limit.",
        )
    if budget.limit_amount <= 0:
        raise ValueError("Budget health evidence requires a positive limit.")
    observed_ratio = budget.observed_spending / budget.limit_amount
    projected_ratio = budget.pace_projected_spending / budget.limit_amount
    pressure = max(observed_ratio, projected_ratio)
    rating = (
        _ONE
        if pressure <= _ONE
        else _clamp(_ONE - ((pressure - _ONE) / Decimal("0.50")))
    )
    reason = (
        FinancialHealthReasonCode.BUDGET_WITHIN_LIMIT
        if pressure <= _ONE
        else FinancialHealthReasonCode.BUDGET_PRESSURE
    )
    return _available(
        FinancialHealthFactor.BUDGET_ADHERENCE,
        rating=rating,
        observed=pressure,
        benchmark=_ONE,
        reasons=(reason,),
        explanation=(
            "The larger of actual and transparent pace-projected budget "
            "utilization is compared with the stored overall limit."
        ),
    )


def _stability_factor(
    buckets: tuple[CashFlowBucketAggregate, ...],
    *,
    period_date_from: date,
    period_date_to: date,
) -> FinancialHealthFactorResult:
    complete_buckets = tuple(
        item
        for item in buckets
        if item.period_start >= period_date_from
        and _month_end(item.period_start) <= period_date_to
    )
    period_day_count = (period_date_to - period_date_from).days + 1
    if period_day_count < 90 or len(complete_buckets) < 3:
        return _unavailable(
            FinancialHealthFactor.CASH_FLOW_STABILITY,
            FinancialHealthReasonCode.CASH_FLOW_HISTORY_INSUFFICIENT,
            "Cash-flow stability requires at least 90 days and three complete monthly buckets.",
        )
    average_income = sum(
        (item.gross_income for item in complete_buckets), _ZERO
    ) / Decimal(len(complete_buckets))
    if average_income <= 0:
        return _unavailable(
            FinancialHealthFactor.CASH_FLOW_STABILITY,
            FinancialHealthReasonCode.INCOME_UNAVAILABLE,
            "Cash-flow stability needs positive average monthly income.",
        )
    net_values = tuple(item.net_cash_flow for item in complete_buckets)
    average_net = sum(net_values, _ZERO) / Decimal(len(net_values))
    mean_absolute_deviation = sum(
        (abs(value - average_net) for value in net_values),
        _ZERO,
    ) / Decimal(len(net_values))
    volatility = _clamp(mean_absolute_deviation / average_income)
    positive_ratio = Decimal(sum(value >= 0 for value in net_values)) / Decimal(
        len(net_values)
    )
    rating = Decimal("0.60") * positive_ratio + Decimal("0.40") * (_ONE - volatility)
    reason = (
        FinancialHealthReasonCode.CASH_FLOW_STABLE
        if rating >= Decimal("0.70")
        else FinancialHealthReasonCode.CASH_FLOW_VOLATILE
    )
    return _available(
        FinancialHealthFactor.CASH_FLOW_STABILITY,
        rating=rating,
        observed=rating,
        benchmark=Decimal("0.70"),
        reasons=(reason,),
        explanation=(
            "The index combines non-negative monthly cash-flow frequency "
            "(60%) with net-cash-flow consistency (40%)."
        ),
    )


def _concentration_factor(
    categories: tuple[CategoryAggregate, ...],
) -> FinancialHealthFactorResult:
    count = sum(item.transaction_count for item in categories)
    categorized_expense = sum((item.amount for item in categories), _ZERO)
    if count < 5 or categorized_expense <= 0:
        return _unavailable(
            FinancialHealthFactor.SPENDING_CONCENTRATION,
            FinancialHealthReasonCode.CATEGORY_EVIDENCE_INSUFFICIENT,
            "Spending concentration requires five categorized expense transactions.",
        )
    top_share = max(item.amount for item in categories) / categorized_expense
    if top_share <= Decimal("0.25"):
        rating = _ONE
    elif top_share >= Decimal("0.75"):
        rating = _ZERO
    else:
        rating = _ONE - ((top_share - Decimal("0.25")) / Decimal("0.50"))
    reason = (
        FinancialHealthReasonCode.SPENDING_DIVERSIFIED
        if top_share <= Decimal("0.50")
        else FinancialHealthReasonCode.SPENDING_CONCENTRATED
    )
    return _available(
        FinancialHealthFactor.SPENDING_CONCENTRATION,
        rating=rating,
        observed=top_share,
        benchmark=Decimal("0.25"),
        reasons=(reason,),
        explanation=(
            "The largest canonical expense category's share is scored from "
            "full points at 25% or less to zero at 75% or more."
        ),
    )


def _completeness_factor(
    summary: AnalyticsSummaryAggregate,
    profile: FinancialHealthProfileAggregate,
) -> FinancialHealthFactorResult:
    sample = _clamp(Decimal(summary.eligible_transaction_count) / Decimal("30"))
    coverage = (
        Decimal(summary.categorized_transaction_count)
        / Decimal(summary.eligible_transaction_count)
        if summary.eligible_transaction_count
        else _ZERO
    )
    profile_complete = (
        _ONE
        if profile.profile_completion_status is ProfileCompletionStatus.COMPLETE
        else _ZERO
    )
    rating = (
        Decimal("0.50") * coverage
        + Decimal("0.30") * sample
        + Decimal("0.20") * profile_complete
    )
    reason = (
        FinancialHealthReasonCode.DATA_COMPLETE
        if rating >= Decimal("0.90")
        else FinancialHealthReasonCode.DATA_INCOMPLETE
    )
    return _available(
        FinancialHealthFactor.DATA_COMPLETENESS,
        rating=rating,
        observed=rating,
        benchmark=Decimal("0.90"),
        reasons=(reason,),
        explanation=(
            "The index combines category coverage (50%), sample adequacy "
            "at 30 transactions (30%), and profile completion (20%)."
        ),
    )


def _debt_rating(burden: Decimal) -> Decimal:
    if burden <= Decimal("0.10"):
        return _ONE
    if burden < Decimal("0.20"):
        return _ONE - ((burden - Decimal("0.10")) / Decimal("0.10") * Decimal("0.20"))
    if burden < Decimal("0.30"):
        return Decimal("0.80") - (
            (burden - Decimal("0.20")) / Decimal("0.10") * Decimal("0.30")
        )
    if burden < Decimal("0.50"):
        return Decimal("0.50") - (
            (burden - Decimal("0.30")) / Decimal("0.20") * Decimal("0.50")
        )
    return _ZERO


def _available(
    factor: FinancialHealthFactor,
    *,
    rating: Decimal,
    observed: Decimal,
    benchmark: Decimal,
    reasons: tuple[FinancialHealthReasonCode, ...],
    explanation: str,
) -> FinancialHealthFactorResult:
    bounded = _clamp(rating)
    return FinancialHealthFactorResult(
        factor=factor,
        configured_weight=_WEIGHTS[factor],
        status=FinancialHealthFactorStatus.AVAILABLE,
        factor_score=_score(bounded * Decimal("100")),
        observed_value=_ratio(observed),
        benchmark_value=_ratio(benchmark),
        effective_weight=_ZERO,
        contribution_points=_ZERO,
        reason_codes=reasons,
        explanation=explanation,
    )


def _unavailable(
    factor: FinancialHealthFactor,
    reason: FinancialHealthReasonCode,
    explanation: str,
) -> FinancialHealthFactorResult:
    return FinancialHealthFactorResult(
        factor=factor,
        configured_weight=_WEIGHTS[factor],
        status=FinancialHealthFactorStatus.UNAVAILABLE,
        factor_score=None,
        observed_value=None,
        benchmark_value=None,
        effective_weight=_ZERO,
        contribution_points=_ZERO,
        reason_codes=(reason,),
        explanation=explanation,
    )


def _apply_effective_weight(
    factor: FinancialHealthFactorResult,
    available_weight: Decimal,
) -> FinancialHealthFactorResult:
    if factor.status is FinancialHealthFactorStatus.UNAVAILABLE:
        return factor
    effective = factor.configured_weight / available_weight * Decimal("100")
    contribution = effective * (factor.factor_score or _ZERO) / Decimal("100")
    return replace(
        factor,
        effective_weight=_score(effective),
        contribution_points=_score(contribution),
    )


def _clamp(value: Decimal) -> Decimal:
    return min(_ONE, max(_ZERO, value))


def _score(value: Decimal) -> Decimal:
    return value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _ratio(value: Decimal) -> Decimal:
    return value.quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_EVEN)


def _month_end(value: date) -> date:
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return next_month - timedelta(days=1)
