"""Deterministic financial-health policy tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from falcon_api.analytics.health_score import (
    BudgetHealthEvidence,
    FinancialHealthFactor,
    FinancialHealthFactorStatus,
    FinancialHealthReasonCode,
    FinancialHealthScoreStatus,
    evaluate_financial_health,
)
from falcon_api.analytics.types import (
    AnalyticsSummaryAggregate,
    CashFlowBucketAggregate,
    CategoryAggregate,
    FinancialHealthProfileAggregate,
)
from falcon_api.models.enums import CategoryKind, ProfileCompletionStatus


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
        source_last_updated_at=(
            datetime(2026, 8, 24, 8, tzinfo=UTC) if eligible else None
        ),
    )


def _profile(
    *,
    liquid: str = "100000",
    liabilities: int = 1,
    payments: int = 1,
    monthly_payment: str = "2000",
    target: str | None = "3",
) -> FinancialHealthProfileAggregate:
    return FinancialHealthProfileAggregate(
        profile_completion_status=ProfileCompletionStatus.COMPLETE,
        emergency_fund_target_months=(Decimal(target) if target is not None else None),
        liquid_balance=Decimal(liquid),
        liability_account_count=liabilities,
        liability_payment_count=payments,
        monthly_debt_payment=Decimal(monthly_payment),
        source_last_updated_at=datetime(2026, 8, 24, 8, tzinfo=UTC),
    )


def _buckets() -> tuple[CashFlowBucketAggregate, ...]:
    return tuple(
        CashFlowBucketAggregate(
            period_start=date(2026, month, 1),
            gross_income=Decimal("10000"),
            total_expense=Decimal(expense),
            transaction_count=10,
        )
        for month, expense in ((5, "6500"), (6, "7000"), (7, "7200"), (8, "7300"))
    )


def _categories() -> tuple[CategoryAggregate, ...]:
    return tuple(
        CategoryAggregate(
            category_id=uuid4(),
            parent_category_id=None,
            name=name,
            classification_code=code,
            kind=CategoryKind.EXPENSE,
            amount=Decimal(amount),
            transaction_count=count,
        )
        for name, code, amount, count in (
            ("Housing", "rent", "9000", 4),
            ("Food", "groceries", "7000", 12),
            ("Transport", "fuel", "6000", 10),
            ("Other", "other_expense", "5000", 10),
        )
    )


def test_complete_score_exposes_all_weights_and_contributions() -> None:
    analysis = evaluate_financial_health(
        summary=_summary(),
        cash_flow_buckets=_buckets(),
        expense_categories=_categories(),
        profile=_profile(),
        period_date_from=date(2026, 5, 1),
        period_date_to=date(2026, 8, 24),
        budget=BudgetHealthEvidence(
            limit_amount=Decimal("30000"),
            observed_spending=Decimal("28000"),
            pace_projected_spending=Decimal("29000"),
        ),
    )

    assert analysis.status is FinancialHealthScoreStatus.COMPLETE
    assert analysis.score is not None
    assert Decimal("0") <= analysis.score <= Decimal("100")
    assert analysis.available_weight == Decimal("100.00")
    assert tuple(item.factor for item in analysis.factors) == tuple(
        FinancialHealthFactor
    )
    assert sum(item.configured_weight for item in analysis.factors) == 100
    assert sum(item.contribution_points for item in analysis.factors) == (
        analysis.score
    )
    assert all(
        item.status is FinancialHealthFactorStatus.AVAILABLE
        for item in analysis.factors
    )


def test_missing_budget_and_short_history_produce_reweighted_partial_score() -> None:
    analysis = evaluate_financial_health(
        summary=_summary(),
        cash_flow_buckets=_buckets()[:1],
        expense_categories=_categories(),
        profile=_profile(liabilities=0, payments=0, monthly_payment="0"),
        period_date_from=date(2026, 8, 1),
        period_date_to=date(2026, 8, 24),
        budget=None,
    )

    assert analysis.status is FinancialHealthScoreStatus.PARTIAL
    assert analysis.available_weight == Decimal("75.00")
    assert analysis.score is not None
    missing = {item.factor: item for item in analysis.factors}
    assert missing[FinancialHealthFactor.BUDGET_ADHERENCE].reason_codes == (
        FinancialHealthReasonCode.BUDGET_NOT_SELECTED,
    )
    assert missing[FinancialHealthFactor.CASH_FLOW_STABILITY].reason_codes == (
        FinancialHealthReasonCode.CASH_FLOW_HISTORY_INSUFFICIENT,
    )
    assert missing[FinancialHealthFactor.BUDGET_ADHERENCE].effective_weight == 0
    assert sum(item.contribution_points for item in analysis.factors) == (
        analysis.score
    )


def test_thin_transaction_history_withholds_composite_score() -> None:
    analysis = evaluate_financial_health(
        summary=_summary(eligible=9, categorized=9),
        cash_flow_buckets=(),
        expense_categories=_categories(),
        profile=_profile(liabilities=0, payments=0, monthly_payment="0"),
        period_date_from=date(2026, 8, 1),
        period_date_to=date(2026, 8, 24),
        budget=None,
    )

    assert analysis.status is FinancialHealthScoreStatus.UNAVAILABLE
    assert analysis.score is None
    assert all(item.effective_weight == 0 for item in analysis.factors)
    assert "at least 10 eligible transactions" in analysis.explanation


def test_missing_liability_payment_abstains_instead_of_understating_debt() -> None:
    analysis = evaluate_financial_health(
        summary=_summary(),
        cash_flow_buckets=_buckets(),
        expense_categories=_categories(),
        profile=_profile(liabilities=2, payments=1),
        period_date_from=date(2026, 5, 1),
        period_date_to=date(2026, 8, 24),
        budget=None,
    )

    debt = next(
        item
        for item in analysis.factors
        if item.factor is FinancialHealthFactor.DEBT_BURDEN
    )
    assert debt.status is FinancialHealthFactorStatus.UNAVAILABLE
    assert debt.reason_codes == (FinancialHealthReasonCode.LIABILITY_TERMS_INCOMPLETE,)


def test_zero_income_and_expense_make_denominator_factors_unavailable() -> None:
    analysis = evaluate_financial_health(
        summary=_summary(income="0", expense="0", eligible=10, categorized=10),
        cash_flow_buckets=(),
        expense_categories=(),
        profile=_profile(liabilities=1, payments=1),
        period_date_from=date(2026, 8, 1),
        period_date_to=date(2026, 8, 30),
        budget=BudgetHealthEvidence(
            limit_amount=None,
            observed_spending=Decimal("0"),
            pace_projected_spending=Decimal("0"),
        ),
    )

    by_factor = {item.factor: item for item in analysis.factors}
    assert by_factor[FinancialHealthFactor.SAVINGS_RATE].reason_codes == (
        FinancialHealthReasonCode.INCOME_UNAVAILABLE,
    )
    assert by_factor[FinancialHealthFactor.EMERGENCY_FUND].reason_codes == (
        FinancialHealthReasonCode.EXPENSE_BASELINE_UNAVAILABLE,
    )
    assert by_factor[FinancialHealthFactor.BUDGET_ADHERENCE].reason_codes == (
        FinancialHealthReasonCode.BUDGET_LIMIT_UNAVAILABLE,
    )
    assert by_factor[FinancialHealthFactor.DEBT_BURDEN].factor_score == Decimal("0.00")


def test_default_emergency_target_is_disclosed_when_profile_target_is_absent() -> None:
    analysis = evaluate_financial_health(
        summary=_summary(),
        cash_flow_buckets=(),
        expense_categories=_categories(),
        profile=_profile(target=None),
        period_date_from=date(2026, 8, 1),
        period_date_to=date(2026, 8, 30),
        budget=None,
    )

    emergency = next(
        item
        for item in analysis.factors
        if item.factor is FinancialHealthFactor.EMERGENCY_FUND
    )
    assert emergency.benchmark_value == Decimal("3.000000")
    assert FinancialHealthReasonCode.DEFAULT_EMERGENCY_TARGET in (
        emergency.reason_codes
    )


@pytest.mark.parametrize(
    ("income", "expense", "expected_score", "reason"),
    [
        ("100", "110", "0.00", FinancialHealthReasonCode.NON_POSITIVE_SAVINGS),
        ("100", "95", "20.00", FinancialHealthReasonCode.POSITIVE_SAVINGS),
        ("100", "85", "55.00", FinancialHealthReasonCode.POSITIVE_SAVINGS),
        ("100", "75", "85.00", FinancialHealthReasonCode.POSITIVE_SAVINGS),
    ],
)
def test_savings_factor_uses_all_piecewise_policy_bands(
    income: str,
    expense: str,
    expected_score: str,
    reason: FinancialHealthReasonCode,
) -> None:
    analysis = evaluate_financial_health(
        summary=_summary(income=income, expense=expense),
        cash_flow_buckets=(),
        expense_categories=(),
        profile=_profile(liabilities=0, payments=0, monthly_payment="0"),
        period_date_from=date(2026, 8, 1),
        period_date_to=date(2026, 8, 30),
        budget=None,
    )

    savings = next(
        item
        for item in analysis.factors
        if item.factor is FinancialHealthFactor.SAVINGS_RATE
    )
    assert savings.factor_score == Decimal(expected_score)
    assert savings.reason_codes == (reason,)


def test_policy_rejects_invalid_period_and_budget_limit() -> None:
    values = {
        "summary": _summary(),
        "cash_flow_buckets": (),
        "expense_categories": (),
        "profile": _profile(),
    }
    with pytest.raises(ValueError, match="period dates"):
        evaluate_financial_health(
            **values,
            period_date_from=date(2026, 8, 2),
            period_date_to=date(2026, 8, 1),
            budget=None,
        )
    with pytest.raises(ValueError, match="positive limit"):
        evaluate_financial_health(
            **values,
            period_date_from=date(2026, 8, 1),
            period_date_to=date(2026, 8, 30),
            budget=BudgetHealthEvidence(
                limit_amount=Decimal("0"),
                observed_spending=Decimal("0"),
                pace_projected_spending=Decimal("0"),
            ),
        )


def test_stability_abstains_without_income_and_flags_volatile_history() -> None:
    no_income = tuple(
        CashFlowBucketAggregate(
            period_start=date(2026, month, 1),
            gross_income=Decimal("0"),
            total_expense=Decimal("100"),
            transaction_count=3,
        )
        for month in (5, 6, 7)
    )
    analysis = evaluate_financial_health(
        summary=_summary(),
        cash_flow_buckets=no_income,
        expense_categories=_categories(),
        profile=_profile(),
        period_date_from=date(2026, 5, 1),
        period_date_to=date(2026, 7, 31),
        budget=None,
    )
    stability = next(
        item
        for item in analysis.factors
        if item.factor is FinancialHealthFactor.CASH_FLOW_STABILITY
    )
    assert stability.reason_codes == (FinancialHealthReasonCode.INCOME_UNAVAILABLE,)

    volatile = (
        CashFlowBucketAggregate(
            period_start=date(2026, 5, 1),
            gross_income=Decimal("1000"),
            total_expense=Decimal("0"),
            transaction_count=3,
        ),
        CashFlowBucketAggregate(
            period_start=date(2026, 6, 1),
            gross_income=Decimal("1000"),
            total_expense=Decimal("5000"),
            transaction_count=3,
        ),
        CashFlowBucketAggregate(
            period_start=date(2026, 7, 1),
            gross_income=Decimal("1000"),
            total_expense=Decimal("5000"),
            transaction_count=3,
        ),
    )
    analysis = evaluate_financial_health(
        summary=_summary(),
        cash_flow_buckets=volatile,
        expense_categories=_categories(),
        profile=_profile(),
        period_date_from=date(2026, 5, 1),
        period_date_to=date(2026, 7, 31),
        budget=None,
    )
    stability = next(
        item
        for item in analysis.factors
        if item.factor is FinancialHealthFactor.CASH_FLOW_STABILITY
    )
    assert stability.reason_codes == (FinancialHealthReasonCode.CASH_FLOW_VOLATILE,)


@pytest.mark.parametrize(
    ("amounts", "expected_score", "reason"),
    [
        (
            ("25", "25", "25", "25"),
            "100.00",
            FinancialHealthReasonCode.SPENDING_DIVERSIFIED,
        ),
        (
            ("80", "10", "5", "5"),
            "0.00",
            FinancialHealthReasonCode.SPENDING_CONCENTRATED,
        ),
    ],
)
def test_concentration_factor_covers_policy_boundaries(
    amounts: tuple[str, ...],
    expected_score: str,
    reason: FinancialHealthReasonCode,
) -> None:
    categories = tuple(
        CategoryAggregate(
            category_id=uuid4(),
            parent_category_id=None,
            name=f"Category {index}",
            classification_code=f"category_{index}",
            kind=CategoryKind.EXPENSE,
            amount=Decimal(amount),
            transaction_count=2,
        )
        for index, amount in enumerate(amounts)
    )
    analysis = evaluate_financial_health(
        summary=_summary(),
        cash_flow_buckets=(),
        expense_categories=categories,
        profile=_profile(),
        period_date_from=date(2026, 8, 1),
        period_date_to=date(2026, 8, 30),
        budget=None,
    )
    concentration = next(
        item
        for item in analysis.factors
        if item.factor is FinancialHealthFactor.SPENDING_CONCENTRATION
    )
    assert concentration.factor_score == Decimal(expected_score)
    assert concentration.reason_codes == (reason,)
