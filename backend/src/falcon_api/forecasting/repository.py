"""Owner-, currency-, history-, and cutoff-scoped forecasting observations."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.types import money
from falcon_api.forecasting.periods import ForecastHistoryWindow
from falcon_api.forecasting.semantics import (
    ForecastGranularity,
    normalize_forecast_currency,
)
from falcon_api.forecasting.types import ForecastSourceBucket
from falcon_api.models.account import Account
from falcon_api.models.enums import TransactionStatus, TransactionType
from falcon_api.models.ledger import Transaction


_CASH_FLOW_TYPES = (TransactionType.INCOME, TransactionType.EXPENSE)


class ForecastingRepository:
    """Read canonical observations without accepting an owner from public input."""

    async def list_source_buckets(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        window: ForecastHistoryWindow,
        currency: str,
    ) -> tuple[ForecastSourceBucket, ...]:
        """Return only data visible inside the immutable forecasting boundary."""
        bucket = Transaction.transaction_date
        if ForecastGranularity(window.granularity) is ForecastGranularity.MONTH:
            bucket = cast(
                func.date_trunc("month", Transaction.transaction_date),
                Date,
            )
        gross_income = func.coalesce(
            func.sum(
                case(
                    (
                        Transaction.transaction_type == TransactionType.INCOME,
                        func.abs(Transaction.amount),
                    ),
                    else_=0,
                )
            ),
            0,
        )
        total_expense = func.coalesce(
            func.sum(
                case(
                    (
                        Transaction.transaction_type == TransactionType.EXPENSE,
                        func.abs(Transaction.amount),
                    ),
                    else_=0,
                )
            ),
            0,
        )
        statement = (
            select(
                bucket.label("period_start"),
                gross_income.label("gross_income"),
                total_expense.label("total_expense"),
                func.count().label("transaction_count"),
                func.max(Transaction.updated_at).label("source_last_updated_at"),
            )
            .select_from(Transaction)
            .join(
                Account,
                and_(
                    Account.user_id == Transaction.user_id,
                    Account.id == Transaction.account_id,
                ),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= window.date_from,
                Transaction.transaction_date <= window.date_to,
                Transaction.created_at <= window.data_cutoff_at,
                Transaction.updated_at <= window.data_cutoff_at,
                Account.currency == normalize_forecast_currency(currency),
                Transaction.status == TransactionStatus.POSTED,
                Transaction.transaction_type.in_(_CASH_FLOW_TYPES),
            )
            .group_by(bucket)
            .order_by(bucket.asc())
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            ForecastSourceBucket(
                period_start=row["period_start"],
                gross_income=money(Decimal(row["gross_income"])),
                total_expense=money(Decimal(row["total_expense"])),
                transaction_count=row["transaction_count"],
                source_last_updated_at=row["source_last_updated_at"],
            )
            for row in rows
        )
