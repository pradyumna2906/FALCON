"""SQL and result contracts for owner-scoped financial aggregation."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics import (
    AccountAggregate,
    AnalyticsGranularity,
    AnalyticsPeriod,
    AnalyticsRepository,
    AnalyticsSummaryAggregate,
    CashFlowBucketAggregate,
    CategoryAggregate,
    MerchantAggregate,
)
from falcon_api.models.enums import AccountType, CategoryKind, TransactionType


_PERIOD = AnalyticsPeriod(
    date_from=date(2026, 8, 1),
    date_to=date(2026, 8, 24),
    timezone="Asia/Kolkata",
)
_UPDATED_AT = datetime(2026, 8, 24, 8, 30, tzinfo=UTC)


def _session_with_one(row: dict[str, object]) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    mappings = Mock()
    mappings.one.return_value = row
    execution = Mock()
    execution.mappings.return_value = mappings
    session.execute.return_value = execution
    return session


def _session_with_all(rows: list[dict[str, object]]) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    mappings = Mock()
    mappings.all.return_value = rows
    execution = Mock()
    execution.mappings.return_value = mappings
    session.execute.return_value = execution
    return session


def _compiled(session: AsyncMock) -> tuple[str, dict[str, object]]:
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def _summary_row() -> dict[str, object]:
    return {
        "gross_income": Decimal("10000"),
        "total_expense": Decimal("6250.5"),
        "internal_transfer_volume": Decimal("500"),
        "net_adjustment": Decimal("-2.5"),
        "eligible_transaction_count": 40,
        "categorized_transaction_count": 36,
        "suggested_transaction_count": 2,
        "abstained_transaction_count": 1,
        "pending_count": 3,
        "transfer_entry_count": 4,
        "adjustment_count": 1,
        "other_currency_count": 2,
        "latest_transaction_date": date(2026, 8, 24),
        "source_last_updated_at": _UPDATED_AT,
    }


def test_summary_maps_exact_values_and_derived_cash_flow() -> None:
    session = _session_with_one(_summary_row())

    result = asyncio.run(
        AnalyticsRepository().get_summary(
            session,
            user_id=uuid4(),
            period=_PERIOD,
            currency="inr",
        )
    )

    assert result == AnalyticsSummaryAggregate(
        gross_income=Decimal("10000.0000"),
        total_expense=Decimal("6250.5000"),
        internal_transfer_volume=Decimal("500.0000"),
        net_adjustment=Decimal("-2.5000"),
        eligible_transaction_count=40,
        categorized_transaction_count=36,
        suggested_transaction_count=2,
        abstained_transaction_count=1,
        pending_count=3,
        transfer_entry_count=4,
        adjustment_count=1,
        other_currency_count=2,
        latest_transaction_date=date(2026, 8, 24),
        source_last_updated_at=_UPDATED_AT,
    )
    assert result.net_cash_flow == Decimal("3749.5000")
    assert result.savings_amount == Decimal("3749.5000")


def test_summary_sql_is_owner_date_currency_and_category_safe() -> None:
    session = _session_with_one(_summary_row())
    user_id = uuid4()

    asyncio.run(
        AnalyticsRepository().get_summary(
            session,
            user_id=user_id,
            period=_PERIOD,
            currency="INR",
        )
    )

    query, params = _compiled(session)
    assert "transactions.user_id =" in query
    assert "accounts.user_id = transactions.user_id" in query
    assert "accounts.id = transactions.account_id" in query
    assert "transactions.transaction_date >=" in query
    assert "transactions.transaction_date <=" in query
    assert "accounts.currency =" in query
    assert "accounts.currency !=" in query
    assert "transaction_classifications.user_id = transactions.user_id" in query
    assert "transaction_classifications.transaction_id = transactions.id" in query
    assert "categories.kind = transactions.transaction_type" in query
    assert "categories.is_system IS true" in query
    assert "categories.user_id =" in query
    assert "transactions.transfer_group_id" in query
    assert "GROUP BY transactions.transfer_group_id" in query
    assert "transactions.amount <" in query
    assert "accounts.archived_at" not in query
    assert user_id in params.values()
    assert _PERIOD.date_from in params.values()
    assert _PERIOD.date_to in params.values()
    assert "INR" in params.values()


@pytest.mark.parametrize(
    ("granularity", "uses_month_bucket"),
    [
        (AnalyticsGranularity.DAY, False),
        (AnalyticsGranularity.MONTH, True),
    ],
)
def test_cash_flow_buckets_are_observed_ordered_and_owner_scoped(
    granularity: AnalyticsGranularity,
    uses_month_bucket: bool,
) -> None:
    session = _session_with_all(
        [
            {
                "period_start": date(2026, 8, 1),
                "gross_income": Decimal("5000"),
                "total_expense": Decimal("125.5"),
                "transaction_count": 3,
            }
        ]
    )

    result = asyncio.run(
        AnalyticsRepository().list_cash_flow_buckets(
            session,
            user_id=uuid4(),
            period=_PERIOD,
            currency="INR",
            granularity=granularity,
        )
    )

    assert result == (
        CashFlowBucketAggregate(
            period_start=date(2026, 8, 1),
            gross_income=Decimal("5000.0000"),
            total_expense=Decimal("125.5000"),
            transaction_count=3,
        ),
    )
    assert result[0].net_cash_flow == Decimal("4874.5000")
    query, _ = _compiled(session)
    assert ("date_trunc" in query) is uses_month_bucket
    assert "transactions.user_id =" in query
    assert "accounts.user_id = transactions.user_id" in query
    assert "transactions.status =" in query
    assert "transactions.transaction_type IN" in query
    assert "GROUP BY" in query
    assert "ORDER BY" in query


def test_category_aggregation_requires_compatible_visible_canonical_category() -> None:
    category_id = uuid4()
    parent_id = uuid4()
    session = _session_with_all(
        [
            {
                "category_id": category_id,
                "parent_category_id": parent_id,
                "name": "Food Delivery",
                "classification_code": "food_delivery",
                "kind": CategoryKind.EXPENSE,
                "amount": Decimal("850.75"),
                "transaction_count": 4,
            }
        ]
    )

    result = asyncio.run(
        AnalyticsRepository().list_category_aggregates(
            session,
            user_id=uuid4(),
            period=_PERIOD,
            currency="INR",
            limit=25,
        )
    )

    assert result == (
        CategoryAggregate(
            category_id=category_id,
            parent_category_id=parent_id,
            name="Food Delivery",
            classification_code="food_delivery",
            kind=CategoryKind.EXPENSE,
            amount=Decimal("850.7500"),
            transaction_count=4,
        ),
    )
    query, params = _compiled(session)
    assert "JOIN categories ON categories.id = transactions.category_id" in query
    assert "categories.kind = transactions.transaction_type" in query
    assert "categories.is_system IS true" in query
    assert "categories.is_system IS false" in query
    assert "categories.user_id =" in query
    assert "categories.archived_at" not in query
    assert 25 in params.values()


def test_merchant_aggregation_normalizes_case_and_preserves_unattributed_bucket() -> None:
    session = _session_with_all(
        [
            {
                "normalized_merchant": "swiggy",
                "display_name": "SWIGGY",
                "gross_income": Decimal("0"),
                "total_expense": Decimal("620"),
                "transaction_count": 2,
                "income_transaction_count": 0,
                "expense_transaction_count": 2,
            },
            {
                "normalized_merchant": None,
                "display_name": None,
                "gross_income": Decimal("100"),
                "total_expense": Decimal("0"),
                "transaction_count": 1,
                "income_transaction_count": 1,
                "expense_transaction_count": 0,
            },
        ]
    )

    result = asyncio.run(
        AnalyticsRepository().list_merchant_aggregates(
            session,
            user_id=uuid4(),
            period=_PERIOD,
            currency="INR",
            limit=10,
        )
    )

    assert result == (
        MerchantAggregate(
            normalized_merchant="swiggy",
            display_name="SWIGGY",
            gross_income=Decimal("0.0000"),
            total_expense=Decimal("620.0000"),
            transaction_count=2,
            income_transaction_count=0,
            expense_transaction_count=2,
        ),
        MerchantAggregate(
            normalized_merchant=None,
            display_name=None,
            gross_income=Decimal("100.0000"),
            total_expense=Decimal("0.0000"),
            transaction_count=1,
            income_transaction_count=1,
            expense_transaction_count=0,
        ),
    )
    query, _ = _compiled(session)
    assert "lower(trim(transactions.merchant_name))" in query
    assert "NULLS LAST" in query
    assert "LIMIT" in query
    assert "transactions.description" not in query


def test_account_aggregation_includes_archived_owned_accounts() -> None:
    account_id = uuid4()
    session = _session_with_all(
        [
            {
                "account_id": account_id,
                "name": "Archived Savings",
                "account_type": AccountType.BANK,
                "gross_income": Decimal("7500"),
                "total_expense": Decimal("1250"),
                "transaction_count": 8,
                "income_transaction_count": 2,
                "expense_transaction_count": 6,
            }
        ]
    )

    result = asyncio.run(
        AnalyticsRepository().list_account_aggregates(
            session,
            user_id=uuid4(),
            period=_PERIOD,
            currency="inr",
            limit=50,
        )
    )

    assert result == (
        AccountAggregate(
            account_id=account_id,
            name="Archived Savings",
            account_type=AccountType.BANK,
            gross_income=Decimal("7500.0000"),
            total_expense=Decimal("1250.0000"),
            transaction_count=8,
            income_transaction_count=2,
            expense_transaction_count=6,
        ),
    )
    query, _ = _compiled(session)
    assert "accounts.user_id = transactions.user_id" in query
    assert "accounts.archived_at" not in query
    assert "GROUP BY accounts.id" in query


@pytest.mark.parametrize("currency", ["", "IN", "USDT", "1NR", "ÄBC"])
def test_repository_rejects_invalid_internal_currency(currency: str) -> None:
    session = _session_with_one(_summary_row())

    with pytest.raises(ValueError, match="three-letter"):
        asyncio.run(
            AnalyticsRepository().get_summary(
                session,
                user_id=uuid4(),
                period=_PERIOD,
                currency=currency,
            )
        )

    session.execute.assert_not_awaited()


@pytest.mark.parametrize("limit", [0, 101, True])
def test_dimension_queries_reject_unbounded_limits(limit: int) -> None:
    session = _session_with_all([])

    with pytest.raises(ValueError, match="between 1 and 100"):
        asyncio.run(
            AnalyticsRepository().list_account_aggregates(
                session,
                user_id=uuid4(),
                period=_PERIOD,
                currency="INR",
                limit=limit,
            )
        )

    session.execute.assert_not_awaited()


def test_each_aggregate_surface_uses_one_database_statement() -> None:
    summary_session = _session_with_one(_summary_row())
    empty_sessions = [_session_with_all([]) for _ in range(4)]
    repository = AnalyticsRepository()
    user_id = uuid4()

    asyncio.run(
        repository.get_summary(
            summary_session,
            user_id=user_id,
            period=_PERIOD,
            currency="INR",
        )
    )
    asyncio.run(
        repository.list_cash_flow_buckets(
            empty_sessions[0],
            user_id=user_id,
            period=_PERIOD,
            currency="INR",
            granularity=AnalyticsGranularity.DAY,
        )
    )
    asyncio.run(
        repository.list_category_aggregates(
            empty_sessions[1],
            user_id=user_id,
            period=_PERIOD,
            currency="INR",
        )
    )
    asyncio.run(
        repository.list_merchant_aggregates(
            empty_sessions[2],
            user_id=user_id,
            period=_PERIOD,
            currency="INR",
        )
    )
    asyncio.run(
        repository.list_account_aggregates(
            empty_sessions[3],
            user_id=user_id,
            period=_PERIOD,
            currency="INR",
        )
    )

    summary_session.execute.assert_awaited_once()
    for session in empty_sessions:
        session.execute.assert_awaited_once()


def test_dimension_query_can_be_restricted_to_expenses() -> None:
    session = _session_with_all([])

    result = asyncio.run(
        AnalyticsRepository().list_merchant_aggregates(
            session,
            user_id=uuid4(),
            period=_PERIOD,
            currency="INR",
            transaction_type=TransactionType.EXPENSE,
        )
    )

    assert result == ()
    query, params = _compiled(session)
    assert "transactions.transaction_type =" in query
    assert TransactionType.EXPENSE in params.values()


def test_dimension_query_rejects_transfer_filter() -> None:
    session = _session_with_all([])

    with pytest.raises(ValueError, match="income or expense"):
        asyncio.run(
            AnalyticsRepository().list_account_aggregates(
                session,
                user_id=uuid4(),
                period=_PERIOD,
                currency="INR",
                transaction_type=TransactionType.TRANSFER,
            )
        )

    session.execute.assert_not_awaited()
