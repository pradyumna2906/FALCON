"""Application contracts for authenticated financial analytics."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.application import (
    AnalyticsSelection,
    FinancialAnalyticsService,
)
from falcon_api.analytics.repository import AnalyticsRepository
from falcon_api.analytics.recurring import RecurringDecision
from falcon_api.analytics.semantics import AnalyticsComparisonMode
from falcon_api.analytics.types import (
    AccountAggregate,
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
    CashFlowBucketAggregate,
    CategoryAggregate,
    MerchantAggregate,
    RecurringTransactionRecord,
    SpendingSignalTransactionRecord,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.models.enums import AccountType, CategoryKind, TransactionType


_NOW = datetime(2026, 8, 24, 8, tzinfo=UTC)


def _summary(
    *,
    income: str = "10000",
    expense: str = "6250",
    eligible: int = 40,
    categorized: int = 36,
) -> AnalyticsSummaryAggregate:
    return AnalyticsSummaryAggregate(
        gross_income=Decimal(income),
        total_expense=Decimal(expense),
        internal_transfer_volume=Decimal("500"),
        net_adjustment=Decimal("-10"),
        eligible_transaction_count=eligible,
        categorized_transaction_count=categorized,
        suggested_transaction_count=2 if eligible else 0,
        abstained_transaction_count=1 if eligible else 0,
        pending_count=3,
        transfer_entry_count=4,
        adjustment_count=1,
        other_currency_count=2,
        latest_transaction_date=date(2026, 8, 24) if eligible else None,
        source_last_updated_at=_NOW if eligible else None,
    )


def _service(
    repository: AsyncMock,
) -> FinancialAnalyticsService:
    clock = Mock()
    clock.now.return_value = _NOW
    return FinancialAnalyticsService(repository=repository, clock=clock)


def _selection(
    *,
    comparison: AnalyticsComparisonMode = (
        AnalyticsComparisonMode.PREVIOUS_PERIOD
    ),
    currency: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AnalyticsSelection:
    return AnalyticsSelection(
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        comparison=comparison,
    )


def test_cash_flow_resolves_trusted_defaults_and_previous_period() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    current = _summary()
    previous = _summary(income="8000", expense="6000")
    repository.get_summary.side_effect = [current, previous]
    repository.list_cash_flow_buckets.return_value = (
        CashFlowBucketAggregate(
            period_start=date(2026, 8, 1),
            gross_income=Decimal("10000"),
            total_expense=Decimal("6250"),
            transaction_count=40,
        ),
    )
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    result = asyncio.run(
        _service(repository).cash_flow(
            session,
            user_id=user_id,
            trusted_timezone="Asia/Kolkata",
            default_currency="INR",
            selection=_selection(),
            granularity=AnalyticsGranularity.MONTH,
        )
    )

    assert result.context.currency == "INR"
    assert result.context.period.date_from == date(2026, 8, 1)
    assert result.context.period.date_to == date(2026, 8, 24)
    assert result.context.comparison_period is not None
    assert result.context.comparison_period.date_from == date(2026, 7, 8)
    assert result.context.comparison_period.date_to == date(2026, 7, 31)
    assert result.metrics.net_cash_flow.value == Decimal("3750.0000")
    assert result.metrics.savings_rate.value == Decimal("0.375000")
    assert result.previous_period is not None
    assert result.previous_period.net_cash_flow.value == Decimal("2000.0000")
    assert result.series[0].net_cash_flow.value == Decimal("3750.0000")
    assert result.context.completeness.classification_coverage == Decimal(
        "0.900000"
    )
    calls = repository.get_summary.await_args_list
    assert calls[0].kwargs["user_id"] == user_id
    assert calls[0].kwargs["currency"] == "INR"
    assert calls[1].kwargs["period"].date_to == date(2026, 7, 31)
    repository.list_cash_flow_buckets.assert_awaited_once_with(
        session,
        user_id=user_id,
        period=calls[0].kwargs["period"],
        currency="INR",
        granularity=AnalyticsGranularity.MONTH,
    )


def test_cash_flow_can_disable_comparison_and_select_currency() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    repository.get_summary.return_value = _summary(income="0", expense="0")
    repository.list_cash_flow_buckets.return_value = ()

    result = asyncio.run(
        _service(repository).cash_flow(
            AsyncMock(spec=AsyncSession),
            user_id=uuid4(),
            trusted_timezone="UTC",
            default_currency="INR",
            selection=_selection(
                comparison=AnalyticsComparisonMode.NONE,
                currency="usd",
                date_from=date(2026, 8, 10),
                date_to=date(2026, 8, 24),
            ),
            granularity=AnalyticsGranularity.DAY,
        )
    )

    assert result.context.currency == "USD"
    assert result.context.comparison_period is None
    assert result.previous_period is None
    assert result.metrics.savings_rate.value is None
    assert result.series == ()
    repository.get_summary.assert_awaited_once()
    assert repository.get_summary.await_args.kwargs["currency"] == "USD"


def test_spending_returns_expense_only_distributions_and_shares() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    current = _summary(expense="1000")
    previous = _summary(expense="800")
    repository.get_summary.side_effect = [current, previous]
    category_id = uuid4()
    parent_id = uuid4()
    account_id = uuid4()
    repository.list_category_aggregates.return_value = (
        CategoryAggregate(
            category_id=category_id,
            parent_category_id=parent_id,
            name="Food Delivery",
            classification_code="food_delivery",
            kind=CategoryKind.EXPENSE,
            amount=Decimal("600"),
            transaction_count=3,
        ),
    )
    repository.list_merchant_aggregates.return_value = (
        MerchantAggregate(
            normalized_merchant="swiggy",
            display_name="Swiggy",
            gross_income=Decimal("0"),
            total_expense=Decimal("400"),
            transaction_count=2,
            income_transaction_count=0,
            expense_transaction_count=2,
        ),
    )
    repository.list_account_aggregates.return_value = (
        AccountAggregate(
            account_id=account_id,
            name="Primary Bank",
            account_type=AccountType.BANK,
            gross_income=Decimal("0"),
            total_expense=Decimal("1000"),
            transaction_count=5,
            income_transaction_count=0,
            expense_transaction_count=5,
        ),
    )
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    result = asyncio.run(
        _service(repository).spending(
            session,
            user_id=user_id,
            trusted_timezone="Asia/Kolkata",
            default_currency="INR",
            selection=_selection(),
            limit=10,
        )
    )

    assert result.total_expense.value == Decimal("1000.0000")
    assert result.previous_period_total_expense is not None
    assert result.previous_period_total_expense.value == Decimal("800.0000")
    assert result.categories[0].category_id == category_id
    assert result.categories[0].share.value == Decimal("0.600000")
    assert result.merchants[0].share.value == Decimal("0.400000")
    assert result.merchants[0].transaction_count == 2
    assert result.accounts[0].share.value == Decimal("1.000000")
    assert result.accounts[0].transaction_count == 5
    for method in (
        repository.list_category_aggregates,
        repository.list_merchant_aggregates,
        repository.list_account_aggregates,
    ):
        method.assert_awaited_once_with(
            session,
            user_id=user_id,
            period=repository.get_summary.await_args_list[0].kwargs["period"],
            currency="INR",
            limit=10,
            transaction_type=TransactionType.EXPENSE,
        )


def test_future_period_fails_before_database_access() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            _service(repository).cash_flow(
                AsyncMock(spec=AsyncSession),
                user_id=uuid4(),
                trusted_timezone="Asia/Kolkata",
                default_currency="INR",
                selection=_selection(
                    date_from=date(2026, 8, 25),
                    date_to=date(2026, 8, 25),
                ),
                granularity=AnalyticsGranularity.DAY,
            )
        )

    assert captured.value.code == "analytics_date_in_future"
    repository.get_summary.assert_not_awaited()


def test_spending_zero_data_is_successful_and_empty() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    repository.get_summary.return_value = _summary(
        income="0",
        expense="0",
        eligible=0,
        categorized=0,
    )
    repository.list_category_aggregates.return_value = ()
    repository.list_merchant_aggregates.return_value = ()
    repository.list_account_aggregates.return_value = ()

    result = asyncio.run(
        _service(repository).spending(
            AsyncMock(spec=AsyncSession),
            user_id=uuid4(),
            trusted_timezone="UTC",
            default_currency="INR",
            selection=_selection(comparison=AnalyticsComparisonMode.NONE),
            limit=25,
        )
    )

    assert result.total_expense.value == Decimal("0.0000")
    assert result.previous_period_total_expense is None
    assert result.categories == ()
    assert result.merchants == ()
    assert result.accounts == ()
    assert result.context.completeness.classification_coverage is None


def test_recurring_composes_owner_scoped_evidence_and_hides_abstentions() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    repository.get_summary.return_value = _summary(expense="3196")
    stable = tuple(
        RecurringTransactionRecord(
            transaction_date=observed,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("799"),
            normalized_merchant="netflix",
            display_name="Netflix",
            classification_code="streaming",
            category_name="Streaming",
        )
        for observed in (
            date(2026, 5, 1),
            date(2026, 6, 1),
            date(2026, 7, 1),
            date(2026, 8, 1),
        )
    )
    irregular = tuple(
        RecurringTransactionRecord(
            transaction_date=observed,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("100"),
            normalized_merchant="irregular",
            display_name="Irregular",
            classification_code=None,
            category_name=None,
        )
        for observed in (
            date(2026, 5, 2),
            date(2026, 5, 3),
            date(2026, 8, 20),
        )
    )
    repository.list_recurring_transactions.return_value = stable + irregular
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    result = asyncio.run(
        _service(repository).recurring(
            session,
            user_id=user_id,
            trusted_timezone="Asia/Kolkata",
            default_currency="INR",
            selection=_selection(
                date_from=date(2026, 5, 1),
                date_to=date(2026, 8, 24),
            ),
            minimum_occurrences=3,
            limit=25,
            include_abstained=False,
        )
    )

    assert result.context.comparison_period is None
    assert result.summary.candidate_pattern_count == 2
    assert result.summary.detected_pattern_count == 1
    assert result.summary.abstained_pattern_count == 1
    assert result.summary.returned_pattern_count == 1
    assert result.summary.truncated is False
    assert result.summary.detected_expense_observed.value == Decimal(
        "3196.0000"
    )
    assert result.summary.detected_income_observed.value == Decimal("0.0000")
    assert result.patterns[0].decision is RecurringDecision.DETECTED
    repository.get_summary.assert_awaited_once()
    repository.list_recurring_transactions.assert_awaited_once_with(
        session,
        user_id=user_id,
        period=repository.get_summary.await_args.kwargs["period"],
        currency="INR",
    )


def test_recurring_zero_data_and_limit_are_successful_and_bounded() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    repository.get_summary.return_value = _summary(
        income="0",
        expense="0",
        eligible=0,
        categorized=0,
    )
    repository.list_recurring_transactions.return_value = ()

    result = asyncio.run(
        _service(repository).recurring(
            AsyncMock(spec=AsyncSession),
            user_id=uuid4(),
            trusted_timezone="UTC",
            default_currency="INR",
            selection=_selection(),
            minimum_occurrences=3,
            limit=1,
            include_abstained=True,
        )
    )

    assert result.summary.candidate_pattern_count == 0
    assert result.summary.returned_pattern_count == 0
    assert result.summary.truncated is False
    assert result.patterns == ()


def test_recurring_applies_pattern_limit_after_complete_detection() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    repository.get_summary.return_value = _summary()
    records = []
    for merchant, amount in (("alpha", "100"), ("beta", "200")):
        records.extend(
            RecurringTransactionRecord(
                transaction_date=observed,
                transaction_type=TransactionType.EXPENSE,
                amount=Decimal(amount),
                normalized_merchant=merchant,
                display_name=merchant.title(),
                classification_code=None,
                category_name=None,
            )
            for observed in (
                date(2026, 6, 1),
                date(2026, 7, 1),
                date(2026, 8, 1),
            )
        )
    repository.list_recurring_transactions.return_value = tuple(records)

    result = asyncio.run(
        _service(repository).recurring(
            AsyncMock(spec=AsyncSession),
            user_id=uuid4(),
            trusted_timezone="UTC",
            default_currency="INR",
            selection=_selection(
                date_from=date(2026, 6, 1),
                date_to=date(2026, 8, 24),
            ),
            minimum_occurrences=3,
            limit=1,
            include_abstained=True,
        )
    )

    assert result.summary.candidate_pattern_count == 2
    assert result.summary.detected_pattern_count == 2
    assert result.summary.returned_pattern_count == 1
    assert result.summary.truncated is True
    assert result.summary.detected_expense_observed.value == Decimal("900.0000")
    assert result.patterns[0].normalized_merchant == "beta"


def test_spending_signals_compose_owner_scoped_evidence_and_limit() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    repository.get_summary.return_value = _summary(
        expense="75",
        eligible=5,
        categorized=2,
    )
    repository.list_spending_signal_transactions.return_value = (
        SpendingSignalTransactionRecord(
            transaction_date=date(2026, 8, 2),
            amount=Decimal("25"),
            normalized_merchant="bank",
            display_name="Bank",
            classification_code="bank_charges",
            category_name="Bank Charges",
        ),
        SpendingSignalTransactionRecord(
            transaction_date=date(2026, 8, 9),
            amount=Decimal("50"),
            normalized_merchant="bank",
            display_name="Bank",
            classification_code="bank_charges",
            category_name="Bank Charges",
        ),
    )
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    result = asyncio.run(
        _service(repository).spending_signals(
            session,
            user_id=user_id,
            trusted_timezone="Asia/Kolkata",
            default_currency="INR",
            selection=_selection(comparison=AnalyticsComparisonMode.NONE),
            limit=1,
        )
    )

    assert result.context.comparison_period is None
    assert result.summary.evaluated_transaction_count == 2
    assert result.summary.detected_signal_count == 1
    assert result.summary.potential_leak_signal_count == 1
    assert result.summary.anomaly_signal_count == 0
    assert result.summary.returned_signal_count == 1
    assert result.summary.truncated is False
    assert len(result.evaluations) == 8
    assert result.signals[0].signal_type.value == "bank_charge_leakage"
    assert result.signals[0].observed_amount.value == Decimal("75.0000")
    repository.list_spending_signal_transactions.assert_awaited_once_with(
        session,
        user_id=user_id,
        period=repository.get_summary.await_args.kwargs["period"],
        currency="INR",
    )


def test_spending_signals_zero_data_is_successful_and_explicit() -> None:
    repository = AsyncMock(spec=AnalyticsRepository)
    repository.get_summary.return_value = _summary(
        income="0",
        expense="0",
        eligible=0,
        categorized=0,
    )
    repository.list_spending_signal_transactions.return_value = ()

    result = asyncio.run(
        _service(repository).spending_signals(
            AsyncMock(spec=AsyncSession),
            user_id=uuid4(),
            trusted_timezone="UTC",
            default_currency="INR",
            selection=_selection(comparison=AnalyticsComparisonMode.NONE),
            limit=25,
        )
    )

    assert result.summary.evaluated_transaction_count == 0
    assert result.summary.detected_signal_count == 0
    assert result.signals == ()
    assert all(item.status.value == "insufficient_data" for item in result.evaluations)
