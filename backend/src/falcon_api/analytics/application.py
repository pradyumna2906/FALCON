"""Authenticated application workflows for live financial analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.budgeting import evaluate_budget
from falcon_api.analytics.health_score import (
    BudgetHealthEvidence,
    evaluate_financial_health,
)
from falcon_api.analytics.insights import (
    InsightSeverity,
    prioritize_insights,
)
from falcon_api.analytics.periods import (
    AnalyticsPeriod,
    previous_period,
    resolve_analytics_period,
)
from falcon_api.analytics.recurring import (
    RecurringDecision,
    detect_recurring_patterns,
)
from falcon_api.analytics.repository import AnalyticsRepository
from falcon_api.analytics.semantics import (
    MAX_ANALYTICS_RANGE_DAYS,
    RATIO_QUANTUM,
    AnalyticsComparisonMode,
)
from falcon_api.analytics.spending_signals import (
    SpendingSignalFamily,
    detect_spending_signals,
)
from falcon_api.analytics.types import (
    MAX_ANALYTICS_DIMENSION_ROWS,
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
)
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.models.enums import TransactionType
from falcon_api.schemas.analytics import (
    AnalyticsCompleteness,
    AnalyticsContext,
    AnalyticsExclusions,
    AnalyticsFreshness,
    AnalyticsPeriodResponse,
    BudgetAnalyticsResponse,
    CashFlowAnalyticsResponse,
    CashFlowMetrics,
    CashFlowPoint,
    FinancialHealthScoreResponse,
    InsightAnalyticsResponse,
    InsightAnalyticsSummary,
    MoneyMetric,
    PersonalFinanceInsightResponse,
    RecurringAnalyticsResponse,
    RecurringAnalyticsSummary,
    RecurringPatternResponse,
    SpendingAccount,
    SpendingAnalyticsResponse,
    SpendingCategory,
    SpendingMerchant,
    SpendingSignalAnalyticsResponse,
    SpendingSignalAnalyticsSummary,
    SpendingSignalEvaluationResponse,
    SpendingSignalResponse,
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

    async def spending_signals(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        trusted_timezone: str,
        default_currency: str,
        selection: AnalyticsSelection,
        limit: int,
    ) -> SpendingSignalAnalyticsResponse:
        """Return bounded leak and anomaly evidence without recommendations."""
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
        records = await self._repository.list_spending_signal_transactions(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
        )
        analysis = detect_spending_signals(
            records,
            period=period,
            total_expense=summary.total_expense,
        )
        returned = analysis.signals[:limit]
        leak_count = sum(
            signal.family is SpendingSignalFamily.POTENTIAL_LEAK
            for signal in analysis.signals
        )
        return SpendingSignalAnalyticsResponse(
            context=_context(
                period=period,
                comparison=None,
                currency=currency,
                summary=summary,
                calculated_at=now,
            ),
            summary=SpendingSignalAnalyticsSummary(
                evaluated_transaction_count=len(records),
                detected_signal_count=len(analysis.signals),
                potential_leak_signal_count=leak_count,
                anomaly_signal_count=len(analysis.signals) - leak_count,
                returned_signal_count=len(returned),
                truncated=len(analysis.signals) > len(returned),
            ),
            evaluations=tuple(
                SpendingSignalEvaluationResponse.from_evaluation(item)
                for item in analysis.evaluations
            ),
            signals=tuple(
                SpendingSignalResponse.from_signal(item) for item in returned
            ),
        )

    async def budget(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        trusted_timezone: str,
        budget_id: UUID,
    ) -> BudgetAnalyticsResponse:
        """Return exact usage and bounded pace risk for one owned budget."""
        definition = await self._repository.get_budget_definition(
            session,
            user_id=user_id,
            budget_id=budget_id,
        )
        if definition is None:
            raise ApplicationError(
                code="budget_not_found",
                message="The requested budget was not found.",
                status_code=404,
            )
        now = self._clock.now()
        local_today = resolve_analytics_period(
            date_from=None,
            date_to=None,
            trusted_timezone=trusted_timezone,
            now=now,
        ).date_to
        if definition.period_start_date > local_today:
            raise ApplicationError(
                code="budget_not_started",
                message="Budget analytics are unavailable before the budget starts.",
                status_code=422,
            )
        budget_day_count = (
            definition.period_end_date - definition.period_start_date
        ).days + 1
        if budget_day_count > MAX_ANALYTICS_RANGE_DAYS:
            raise ApplicationError(
                code="budget_period_unsupported",
                message=(
                    "Budget analytics support periods of at most "
                    f"{MAX_ANALYTICS_RANGE_DAYS} days."
                ),
                status_code=422,
            )
        period = resolve_analytics_period(
            date_from=definition.period_start_date,
            date_to=min(local_today, definition.period_end_date),
            trusted_timezone=trusted_timezone,
            now=now,
        )
        summary = await self._repository.get_summary(
            session,
            user_id=user_id,
            period=period,
            currency=definition.currency,
        )
        category_spending = (
            await self._repository.list_budget_category_spending(
                session,
                user_id=user_id,
                budget_id=budget_id,
                period=period,
            )
        )
        analysis = evaluate_budget(
            definition,
            category_spending,
            total_expense=summary.total_expense,
            local_today=local_today,
        )
        return BudgetAnalyticsResponse.from_analysis(
            context=_context(
                period=period,
                comparison=None,
                currency=definition.currency,
                summary=summary,
                calculated_at=now,
            ),
            definition=definition,
            analysis=analysis,
        )

    async def financial_health_score(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        trusted_timezone: str,
        default_currency: str,
        selection: AnalyticsSelection,
        budget_id: UUID | None,
    ) -> FinancialHealthScoreResponse:
        """Return a bounded composite with every factor contribution exposed."""
        now = self._clock.now()
        period, _ = _resolve_periods(
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
        buckets = await self._repository.list_cash_flow_buckets(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            granularity=AnalyticsGranularity.MONTH,
        )
        categories = await self._repository.list_category_aggregates(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            limit=MAX_ANALYTICS_DIMENSION_ROWS,
            transaction_type=TransactionType.EXPENSE,
        )
        profile = await self._repository.get_financial_health_profile(
            session,
            user_id=user_id,
            as_of=period.date_to,
            currency=currency,
        )

        budget_evidence = None
        if budget_id is not None:
            definition = await self._repository.get_budget_definition(
                session,
                user_id=user_id,
                budget_id=budget_id,
            )
            if definition is None:
                raise ApplicationError(
                    code="budget_not_found",
                    message="The requested budget was not found.",
                    status_code=404,
                )
            local_today = resolve_analytics_period(
                date_from=None,
                date_to=None,
                trusted_timezone=trusted_timezone,
                now=now,
            ).date_to
            expected_observed_to = min(local_today, definition.period_end_date)
            if (
                definition.currency != currency
                or definition.period_start_date != period.date_from
                or expected_observed_to != period.date_to
            ):
                raise ApplicationError(
                    code="health_budget_period_mismatch",
                    message=(
                        "The selected budget must match the score currency, "
                        "start date, and observed end date."
                    ),
                    status_code=422,
                )
            budget_analysis = evaluate_budget(
                definition,
                (),
                total_expense=summary.total_expense,
                local_today=local_today,
            )
            budget_evidence = BudgetHealthEvidence(
                limit_amount=definition.overall_limit,
                observed_spending=budget_analysis.overall.spent_amount,
                pace_projected_spending=(
                    budget_analysis.overall.pace_projected_spend
                    or summary.total_expense
                ),
            )

        analysis = evaluate_financial_health(
            summary=summary,
            cash_flow_buckets=buckets,
            expense_categories=categories,
            profile=profile,
            period_date_from=period.date_from,
            period_date_to=period.date_to,
            budget=budget_evidence,
        )
        return FinancialHealthScoreResponse.from_analysis(
            context=_context(
                period=period,
                comparison=None,
                currency=currency,
                summary=summary,
                calculated_at=now,
                additional_source_updated_at=profile.source_last_updated_at,
            ),
            analysis=analysis,
        )

    async def prioritized_insights(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        trusted_timezone: str,
        default_currency: str,
        selection: AnalyticsSelection,
        budget_id: UUID | None,
        limit: int,
    ) -> InsightAnalyticsResponse:
        """Return deterministic next actions from existing analytics evidence."""
        now = self._clock.now()
        period, _ = _resolve_periods(
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
        records = await self._repository.list_spending_signal_transactions(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
        )
        buckets = await self._repository.list_cash_flow_buckets(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            granularity=AnalyticsGranularity.MONTH,
        )
        categories = await self._repository.list_category_aggregates(
            session,
            user_id=user_id,
            period=period,
            currency=currency,
            limit=MAX_ANALYTICS_DIMENSION_ROWS,
            transaction_type=TransactionType.EXPENSE,
        )
        profile = await self._repository.get_financial_health_profile(
            session,
            user_id=user_id,
            as_of=period.date_to,
            currency=currency,
        )

        budget_evidence = None
        if budget_id is not None:
            definition = await self._repository.get_budget_definition(
                session,
                user_id=user_id,
                budget_id=budget_id,
            )
            if definition is None:
                raise ApplicationError(
                    code="budget_not_found",
                    message="The requested budget was not found.",
                    status_code=404,
                )
            local_today = resolve_analytics_period(
                date_from=None,
                date_to=None,
                trusted_timezone=trusted_timezone,
                now=now,
            ).date_to
            expected_observed_to = min(local_today, definition.period_end_date)
            if (
                definition.currency != currency
                or definition.period_start_date != period.date_from
                or expected_observed_to != period.date_to
            ):
                raise ApplicationError(
                    code="insight_budget_period_mismatch",
                    message=(
                        "The selected budget must match the insight currency, "
                        "start date, and observed end date."
                    ),
                    status_code=422,
                )
            budget_analysis = evaluate_budget(
                definition,
                (),
                total_expense=summary.total_expense,
                local_today=local_today,
            )
            budget_evidence = BudgetHealthEvidence(
                limit_amount=definition.overall_limit,
                observed_spending=budget_analysis.overall.spent_amount,
                pace_projected_spending=(
                    budget_analysis.overall.pace_projected_spend
                    or summary.total_expense
                ),
            )

        spending_analysis = detect_spending_signals(
            records,
            period=period,
            total_expense=summary.total_expense,
        )
        health_analysis = evaluate_financial_health(
            summary=summary,
            cash_flow_buckets=buckets,
            expense_categories=categories,
            profile=profile,
            period_date_from=period.date_from,
            period_date_to=period.date_to,
            budget=budget_evidence,
        )
        analysis = prioritize_insights(
            summary=summary,
            health=health_analysis,
            spending_signals=spending_analysis.signals,
        )
        returned = analysis.insights[:limit]
        return InsightAnalyticsResponse(
            context=_context(
                period=period,
                comparison=None,
                currency=currency,
                summary=summary,
                calculated_at=now,
                additional_source_updated_at=profile.source_last_updated_at,
            ),
            status=analysis.status,
            summary=InsightAnalyticsSummary(
                candidate_count=analysis.candidate_count,
                active_insight_count=len(analysis.insights),
                high_severity_count=sum(
                    item.severity is InsightSeverity.HIGH
                    for item in analysis.insights
                ),
                medium_severity_count=sum(
                    item.severity is InsightSeverity.MEDIUM
                    for item in analysis.insights
                ),
                low_severity_count=sum(
                    item.severity is InsightSeverity.LOW
                    for item in analysis.insights
                ),
                returned_insight_count=len(returned),
                truncated=len(returned) < len(analysis.insights),
            ),
            insights=tuple(
                PersonalFinanceInsightResponse.from_insight(item)
                for item in returned
            ),
            explanation=analysis.explanation,
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
    additional_source_updated_at: datetime | None = None,
) -> AnalyticsContext:
    source_last_updated_at = summary.source_last_updated_at
    if additional_source_updated_at is not None and (
        source_last_updated_at is None
        or additional_source_updated_at > source_last_updated_at
    ):
        source_last_updated_at = additional_source_updated_at
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
            source_last_updated_at=source_last_updated_at,
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
