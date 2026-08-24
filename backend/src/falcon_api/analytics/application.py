"""Authenticated application workflows for live financial analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.periods import (
    AnalyticsPeriod,
    previous_period,
    resolve_analytics_period,
)
from falcon_api.analytics.repository import AnalyticsRepository
from falcon_api.analytics.recurring import (
    RecurringDecision,
    detect_recurring_patterns,
)
from falcon_api.analytics.semantics import (
    RATIO_QUANTUM,
    AnalyticsComparisonMode,
)
from falcon_api.analytics.types import (
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
)
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.models.enums import TransactionType
from falcon_api.schemas.analytics import (
    AnalyticsCompleteness,
    AnalyticsContext,
    AnalyticsExclusions,
    AnalyticsFreshness,
    AnalyticsPeriodResponse,
    CashFlowAnalyticsResponse,
    CashFlowMetrics,
    CashFlowPoint,
    MoneyMetric,
    RecurringAnalyticsResponse,
    RecurringAnalyticsSummary,
    RecurringPatternResponse,
    SpendingAccount,
    SpendingAnalyticsResponse,
    SpendingCategory,
    SpendingMerchant,
)


@dataclass(frozen=True, slots=True)
class AnalyticsSelection:
    """Validated client selections excluding trusted owner and timezone."""

    date_from: date | None
    date_to: date | None
    currency: str | None
    comparison: AnalyticsComparisonMode


class FinancialAnalyticsService:
    """Compose exact aggregates into privacy-safe dashboard responses."""

    def __init__(
        self,
        *,
        repository: AnalyticsRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or AnalyticsRepository()
        self._clock = clock or SystemClock()

    async def cash_flow(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        trusted_timezone: str,
        default_currency: str,
        selection: AnalyticsSelection,
        granularity: AnalyticsGranularity,
    ) -> CashFlowAnalyticsResponse:
        """Return headline cash flow, an observed series, and prior values."""
        now = self._clock.now()
        period, comparison = _resolve_periods(
            selection=selection,
            trusted_timezone=trusted_timezone,
            now=now,
        )
        currency = _resolve_currency(
            requested=selection.currency,
            default=default_currency,
        )
        summary = await self._repository.get_summary(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
        )
        series = await self._repository.list_cash_flow_buckets(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            granularity=granularity,
        )
        previous_summary = None
        if comparison is not None:
            previous_summary = await self._repository.get_summary(
                session,
                user_id=user_id,
                period=comparison,
                currency=currency,
            )

        return CashFlowAnalyticsResponse(
            context=_context(
                period=period,
                comparison=comparison,
                currency=currency,
                summary=summary,
                calculated_at=now,
            ),
            granularity=granularity,
            metrics=CashFlowMetrics.from_aggregate(summary),
            previous_period=(
                CashFlowMetrics.from_aggregate(previous_summary)
                if previous_summary is not None
                else None
            ),
            series=tuple(CashFlowPoint.from_aggregate(item) for item in series),
        )

    async def spending(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        trusted_timezone: str,
        default_currency: str,
        selection: AnalyticsSelection,
        limit: int,
    ) -> SpendingAnalyticsResponse:
        """Return expense totals and bounded expense-only distributions."""
        now = self._clock.now()
        period, comparison = _resolve_periods(
            selection=selection,
            trusted_timezone=trusted_timezone,
            now=now,
        )
        currency = _resolve_currency(
            requested=selection.currency,
            default=default_currency,
        )
        summary = await self._repository.get_summary(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
        )
        categories = await self._repository.list_category_aggregates(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            limit=limit,
            transaction_type=TransactionType.EXPENSE,
        )
        merchants = await self._repository.list_merchant_aggregates(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            limit=limit,
            transaction_type=TransactionType.EXPENSE,
        )
        accounts = await self._repository.list_account_aggregates(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            limit=limit,
            transaction_type=TransactionType.EXPENSE,
        )
        previous_summary = None
        if comparison is not None:
            previous_summary = await self._repository.get_summary(
                session,
                user_id=user_id,
                period=comparison,
                currency=currency,
            )

        total_expense = summary.total_expense
        return SpendingAnalyticsResponse(
            context=_context(
                period=period,
                comparison=comparison,
                currency=currency,
                summary=summary,
                calculated_at=now,
            ),
            total_expense=MoneyMetric(value=total_expense),
            previous_period_total_expense=(
                MoneyMetric(value=previous_summary.total_expense)
                if previous_summary is not None
                else None
            ),
            categories=tuple(
                SpendingCategory.from_aggregate(
                    item,
                    share=_share(item.amount, total_expense),
                )
                for item in categories
            ),
            merchants=tuple(
                SpendingMerchant.from_aggregate(
                    item,
                    share=_share(item.total_expense, total_expense),
                )
                for item in merchants
            ),
            accounts=tuple(
                SpendingAccount.from_aggregate(
                    item,
                    share=_share(item.total_expense, total_expense),
                )
                for item in accounts
            ),
        )

    async def recurring(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        trusted_timezone: str,
        default_currency: str,
        selection: AnalyticsSelection,
        minimum_occurrences: int,
        limit: int,
        include_abstained: bool,
    ) -> RecurringAnalyticsResponse:
        """Return detected patterns plus bounded explicit abstentions."""
        now = self._clock.now()
        period = resolve_analytics_period(
            date_from=selection.date_from,
            date_to=selection.date_to,
            trusted_timezone=trusted_timezone,
            now=now,
        )
        currency = _resolve_currency(
            requested=selection.currency,
            default=default_currency,
        )
        summary = await self._repository.get_summary(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
        )
        records = await self._repository.list_recurring_transactions(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
        )
        candidates = detect_recurring_patterns(
            records,
            minimum_occurrences=minimum_occurrences,
        )
        visible = tuple(
            pattern
            for pattern in candidates
            if include_abstained
            or pattern.decision is RecurringDecision.DETECTED
        )
        returned = visible[:limit]
        detected = tuple(
            pattern
            for pattern in candidates
            if pattern.decision is RecurringDecision.DETECTED
        )
        detected_income = sum(
            (
                pattern.observed_total
                for pattern in detected
                if pattern.transaction_type is TransactionType.INCOME
            ),
            start=Decimal("0"),
        )
        detected_expense = sum(
            (
                pattern.observed_total
                for pattern in detected
                if pattern.transaction_type is TransactionType.EXPENSE
            ),
            start=Decimal("0"),
        )
        return RecurringAnalyticsResponse(
            context=_context(
                period=period,
                comparison=None,
                currency=currency,
                summary=summary,
                calculated_at=now,
            ),
            minimum_occurrences=minimum_occurrences,
            summary=RecurringAnalyticsSummary(
                candidate_pattern_count=len(candidates),
                detected_pattern_count=len(detected),
                abstained_pattern_count=len(candidates) - len(detected),
                returned_pattern_count=len(returned),
                truncated=len(visible) > len(returned),
                detected_income_observed=MoneyMetric(value=detected_income),
                detected_expense_observed=MoneyMetric(value=detected_expense),
            ),
            patterns=tuple(
                RecurringPatternResponse.from_pattern(pattern)
                for pattern in returned
            ),
        )


def _resolve_periods(
    *,
    selection: AnalyticsSelection,
    trusted_timezone: str,
    now: datetime,
) -> tuple[AnalyticsPeriod, AnalyticsPeriod | None]:
    period = resolve_analytics_period(
        date_from=selection.date_from,
        date_to=selection.date_to,
        trusted_timezone=trusted_timezone,
        now=now,
    )
    comparison = (
        previous_period(period)
        if selection.comparison is AnalyticsComparisonMode.PREVIOUS_PERIOD
        else None
    )
    return period, comparison


def _resolve_currency(*, requested: str | None, default: str) -> str:
    return (requested or default).strip().upper()


def _context(
    *,
    period: AnalyticsPeriod,
    comparison: AnalyticsPeriod | None,
    currency: str,
    summary: AnalyticsSummaryAggregate,
    calculated_at: datetime,
) -> AnalyticsContext:
    return AnalyticsContext(
        currency=currency,
        period=AnalyticsPeriodResponse.from_period(period),
        comparison_period=(
            AnalyticsPeriodResponse.from_period(comparison)
            if comparison is not None
            else None
        ),
        freshness=AnalyticsFreshness(
            calculated_at=calculated_at,
            source_last_updated_at=summary.source_last_updated_at,
            latest_transaction_date=summary.latest_transaction_date,
        ),
        completeness=AnalyticsCompleteness(
            eligible_transaction_count=summary.eligible_transaction_count,
            categorized_transaction_count=summary.categorized_transaction_count,
            suggested_transaction_count=summary.suggested_transaction_count,
            abstained_transaction_count=summary.abstained_transaction_count,
            exclusions=AnalyticsExclusions(
                pending_count=summary.pending_count,
                transfer_entry_count=summary.transfer_entry_count,
                adjustment_count=summary.adjustment_count,
                other_currency_count=summary.other_currency_count,
            ),
        ),
    )


def _share(amount: Decimal, total: Decimal) -> Decimal | None:
    if total <= 0:
        return None
    return (amount / total).quantize(
        RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
