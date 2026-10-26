"""SQL and mapping tests for owner-scoped forecasting observations."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.forecasting import (
    ForecastGranularity,
    ForecastHistoryWindow,
    ForecastSourceBucket,
    ForecastingRepository,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession


_CUTOFF = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _session_with_all(rows: list[dict[str, object]]) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    mappings = Mock()
    mappings.all.return_value = rows
    execution = Mock()
    execution.mappings.return_value = mappings
    session.execute.return_value = execution
    return session


def _window(granularity: ForecastGranularity) -> ForecastHistoryWindow:
    if granularity is ForecastGranularity.MONTH:
        date_from, date_to = date(2026, 6, 1), date(2026, 8, 31)
    else:
        date_from, date_to = date(2026, 8, 1), date(2026, 8, 31)
    return ForecastHistoryWindow(
        date_from=date_from,
        date_to=date_to,
        timezone="Asia/Kolkata",
        granularity=granularity,
        data_cutoff_at=_CUTOFF,
    )


@pytest.mark.parametrize(
    ("granularity", "uses_month_bucket"),
    [
        (ForecastGranularity.DAY, False),
        (ForecastGranularity.MONTH, True),
    ],
)
def test_source_query_is_owner_currency_history_and_cutoff_scoped(
    granularity: ForecastGranularity, uses_month_bucket: bool
) -> None:
    session = _session_with_all([])
    user_id = uuid4()
    window = _window(granularity)

    result = asyncio.run(
        ForecastingRepository().list_source_buckets(
            session,
            user_id=user_id,
            window=window,
            currency="inr",
        )
    )

    assert result == ()
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    query, params = str(compiled), compiled.params
    assert "transactions.user_id =" in query
    assert "accounts.user_id = transactions.user_id" in query
    assert "accounts.id = transactions.account_id" in query
    assert "transactions.transaction_date >=" in query
    assert "transactions.transaction_date <=" in query
    assert "transactions.created_at <=" in query
    assert "transactions.updated_at <=" in query
    assert "accounts.currency =" in query
    assert "transactions.status =" in query
    assert "transactions.transaction_type IN" in query
    assert ("date_trunc" in query) is uses_month_bucket
    assert "accounts.archived_at" not in query
    assert user_id in params.values()
    assert window.date_from in params.values()
    assert window.date_to in params.values()
    assert _CUTOFF in params.values()
    assert "INR" in params.values()


def test_source_rows_map_to_exact_domain_buckets() -> None:
    updated_at = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)
    session = _session_with_all(
        [
            {
                "period_start": date(2026, 8, 1),
                "gross_income": Decimal("10000"),
                "total_expense": Decimal("6250.5"),
                "transaction_count": 40,
                "source_last_updated_at": updated_at,
            }
        ]
    )

    result = asyncio.run(
        ForecastingRepository().list_source_buckets(
            session,
            user_id=uuid4(),
            window=_window(ForecastGranularity.MONTH),
            currency="INR",
        )
    )

    assert result == (
        ForecastSourceBucket(
            period_start=date(2026, 8, 1),
            gross_income=Decimal("10000.0000"),
            total_expense=Decimal("6250.5000"),
            transaction_count=40,
            source_last_updated_at=updated_at,
        ),
    )
