"""Strict public contracts for financial analytics."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

from falcon_api.analytics.budgeting import (
    BUDGET_POLICY_VERSION,
    BudgetAnalysis,
    BudgetAnalysisStatus,
    BudgetCategoryPerformance,
    BudgetPerformance,
    BudgetRiskLevel,
    BudgetWarningStatus,
)
from falcon_api.analytics.health_score import (
    FINANCIAL_HEALTH_POLICY_VERSION,
    FinancialHealthAnalysis,
    FinancialHealthFactor,
    FinancialHealthFactorResult,
    FinancialHealthFactorStatus,
    FinancialHealthReasonCode,
    FinancialHealthScoreStatus,
)
from falcon_api.analytics.insights import (
    INSIGHT_POLICY_VERSION,
    MAX_INSIGHTS,
    InsightAnalysisStatus,
    InsightCategory,
    InsightConfidence,
    InsightImpactBasis,
    InsightLifecycleState,
    InsightReasonCode,
    InsightSeverity,
    InsightType,
    InsightUrgency,
    PersonalFinanceInsight,
)
from falcon_api.analytics.periods import AnalyticsPeriod
from falcon_api.analytics.recurring import (
    MAX_RECURRING_OCCURRENCES,
    MAX_RECURRING_PATTERNS,
    MIN_RECURRING_OCCURRENCES,
    RECURRING_POLICY_VERSION,
    RecurringCadence,
    RecurringConfidenceBand,
    RecurringDecision,
    RecurringPattern,
    RecurringPatternType,
    RecurringReasonCode,
)
from falcon_api.analytics.semantics import (
    ANALYTICS_CONTRACT_VERSION,
    MAX_ANALYTICS_RANGE_DAYS,
    AnalyticsComparisonMode,
    AnalyticsConfidenceLevel,
    classification_completeness,
)
from falcon_api.analytics.spending_signals import (
    MAX_SPENDING_SIGNALS,
    SPENDING_SIGNAL_POLICY_VERSION,
    SpendingSignal,
    SpendingSignalEvaluation,
    SpendingSignalEvaluationStatus,
    SpendingSignalFamily,
    SpendingSignalReasonCode,
    SpendingSignalSeverity,
    SpendingSignalType,
)
from falcon_api.analytics.types import (
    MAX_ANALYTICS_DIMENSION_ROWS,
    AccountAggregate,
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
    BudgetDefinition,
    CashFlowBucketAggregate,
    CategoryAggregate,
    MerchantAggregate,
)
from falcon_api.models.enums import AccountType, CategoryKind, TransactionType

CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$"),
]
MoneyValue = Annotated[
    Decimal,
    Field(max_digits=19, decimal_places=4),
]
_MONEY_QUANTUM = Decimal("0.0001")
_RATIO_QUANTUM = Decimal("0.000001")
RatioValue = Annotated[
    Decimal,
    Field(max_digits=12, decimal_places=6),
]


class AnalyticsSchema(BaseModel):
    """Forbid undeclared fields and freeze validated analytics data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
    )


class AnalyticsRangeQuery(AnalyticsSchema):
    """Select one bounded range without accepting owner or timezone context."""

    date_from: date | None = None
    date_to: date | None = None
    currency: CurrencyCode | None = None
    comparison: AnalyticsComparisonMode = AnalyticsComparisonMode.PREVIOUS_PERIOD

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        """Use canonical uppercase currency identifiers."""
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_date_window(self) -> "AnalyticsRangeQuery":
        """Require a complete, ordered, bounded explicit range."""
        day_count = _validate_date_range(self.date_from, self.date_to)
        if day_count is None:
            return self
        if self.comparison is AnalyticsComparisonMode.PREVIOUS_PERIOD:
            try:
                self.date_from - timedelta(days=day_count)
            except OverflowError:
                raise ValueError(
                    "The selected range has no representable previous period."
                ) from None
        return self


class CashFlowAnalyticsQuery(AnalyticsRangeQuery):
    """Select a bounded cash-flow series and comparison."""

    granularity: AnalyticsGranularity = AnalyticsGranularity.MONTH


class SpendingAnalyticsQuery(AnalyticsRangeQuery):
    """Select bounded expense distributions and comparison."""

    limit: int = Field(default=25, ge=1, le=MAX_ANALYTICS_DIMENSION_ROWS)


class RecurringAnalyticsQuery(AnalyticsSchema):
    """Select bounded live recurring-pattern evidence."""

    date_from: date | None = None
    date_to: date | None = None
    currency: CurrencyCode | None = None
    minimum_occurrences: int = Field(
        default=MIN_RECURRING_OCCURRENCES,
        ge=MIN_RECURRING_OCCURRENCES,
        le=MAX_RECURRING_OCCURRENCES,
    )
    limit: int = Field(default=25, ge=1, le=MAX_RECURRING_PATTERNS)
    include_abstained: bool = True

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        """Use canonical uppercase currency identifiers."""
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_date_window(self) -> "RecurringAnalyticsQuery":
        """Apply the frozen inclusive analytics range contract."""
        _validate_date_range(self.date_from, self.date_to)
        return self


class SpendingSignalAnalyticsQuery(AnalyticsSchema):
    """Select bounded live leak and anomaly evidence."""

    date_from: date | None = None
    date_to: date | None = None
    currency: CurrencyCode | None = None
    limit: int = Field(default=25, ge=1, le=MAX_SPENDING_SIGNALS)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        """Use canonical uppercase currency identifiers."""
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_date_window(self) -> "SpendingSignalAnalyticsQuery":
        """Apply the frozen inclusive analytics range contract."""
        _validate_date_range(self.date_from, self.date_to)
        return self


class FinancialHealthAnalyticsQuery(AnalyticsSchema):
    """Select bounded health-score evidence without owner-controlled inputs."""

    date_from: date | None = None
    date_to: date | None = None
    currency: CurrencyCode | None = None
    budget_id: UUID | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        """Use canonical uppercase currency identifiers."""
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_date_window(self) -> "FinancialHealthAnalyticsQuery":
        """Apply the frozen inclusive analytics range contract."""
        _validate_date_range(self.date_from, self.date_to)
        return self


class InsightAnalyticsQuery(FinancialHealthAnalyticsQuery):
    """Select a bounded live recommendation set from trusted evidence."""

    limit: int = Field(default=10, ge=1, le=MAX_INSIGHTS)


class AnalyticsPeriodResponse(AnalyticsSchema):
    """Expose the exact inclusive range resolved by the server."""

    date_from: date
    date_to: date
    timezone: str = Field(min_length=1, max_length=64)
    day_count: int = Field(ge=1, le=MAX_ANALYTICS_RANGE_DAYS)

    @classmethod
    def from_period(cls, period: AnalyticsPeriod) -> "AnalyticsPeriodResponse":
        """Build a response without duplicating day-count arithmetic."""
        return cls(
            date_from=period.date_from,
            date_to=period.date_to,
            timezone=period.timezone,
            day_count=period.day_count,
        )

    @model_validator(mode="after")
    def validate_day_count(self) -> "AnalyticsPeriodResponse":
        """Reject inconsistent server-generated period metadata."""
        expected = (self.date_to - self.date_from).days + 1
        if expected != self.day_count:
            raise ValueError("day_count must match the inclusive analytics range.")
        return self


class AnalyticsFreshness(AnalyticsSchema):
    """Describe when live results were calculated and last changed."""

    calculated_at: datetime
    source_last_updated_at: datetime | None
    latest_transaction_date: date | None
    materialized: Literal[False] = False

    @field_validator("calculated_at", "source_last_updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        """Require explicit UTC for unambiguous freshness comparisons."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Analytics freshness timestamps must be timezone-aware.")
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("Analytics freshness timestamps must use UTC.")
        return value

    @model_validator(mode="after")
    def validate_source_time(self) -> "AnalyticsFreshness":
        """Keep a source watermark from appearing newer than its calculation."""
        if (
            self.source_last_updated_at is not None
            and self.source_last_updated_at > self.calculated_at
        ):
            raise ValueError(
                "source_last_updated_at cannot be later than calculated_at."
            )
        return self


class AnalyticsExclusions(AnalyticsSchema):
    """Report why ledger rows did not enter core income/expense metrics."""

    pending_count: int = Field(ge=0)
    transfer_entry_count: int = Field(ge=0)
    adjustment_count: int = Field(ge=0)
    other_currency_count: int = Field(ge=0)


class AnalyticsCompleteness(AnalyticsSchema):
    """Report category coverage without presenting it as model probability."""

    eligible_transaction_count: int = Field(ge=0)
    categorized_transaction_count: int = Field(ge=0)
    suggested_transaction_count: int = Field(ge=0)
    abstained_transaction_count: int = Field(ge=0)
    exclusions: AnalyticsExclusions

    @model_validator(mode="after")
    def validate_counts(self) -> "AnalyticsCompleteness":
        """Keep all classification-quality subsets inside the eligible set."""
        if self.categorized_transaction_count > self.eligible_transaction_count:
            raise ValueError(
                "categorized_transaction_count cannot exceed "
                "eligible_transaction_count."
            )
        unresolved = (
            self.suggested_transaction_count + self.abstained_transaction_count
        )
        if unresolved > (
            self.eligible_transaction_count - self.categorized_transaction_count
        ):
            raise ValueError(
                "Suggested and abstained counts cannot exceed "
                "uncategorized eligibility."
            )
        return self

    @computed_field(return_type=RatioValue | None)
    @property
    def classification_coverage(self) -> Decimal | None:
        """Return the exact count-based canonical-category coverage ratio."""
        coverage, _ = classification_completeness(
            eligible_count=self.eligible_transaction_count,
            categorized_count=self.categorized_transaction_count,
        )
        return coverage

    @computed_field(return_type=AnalyticsConfidenceLevel)
    @property
    def data_confidence(self) -> AnalyticsConfidenceLevel:
        """Return a coverage/sample-size band, never an ML probability."""
        _, confidence = classification_completeness(
            eligible_count=self.eligible_transaction_count,
            categorized_count=self.categorized_transaction_count,
        )
        return confidence


class AnalyticsContext(AnalyticsSchema):
    """Common metadata every future analytics response must carry."""

    contract_version: Literal["2026.1"] = ANALYTICS_CONTRACT_VERSION
    currency: CurrencyCode
    period: AnalyticsPeriodResponse
    comparison_period: AnalyticsPeriodResponse | None
    freshness: AnalyticsFreshness
    completeness: AnalyticsCompleteness

    @field_validator("currency")
    @classmethod
    def normalize_context_currency(cls, value: str) -> str:
        """Serialize the isolated result currency canonically."""
        return value.upper()

    @model_validator(mode="after")
    def validate_context_relationships(self) -> "AnalyticsContext":
        """Keep comparison and freshness metadata bound to the selected period."""
        comparison = self.comparison_period
        if comparison is not None:
            if comparison.timezone != self.period.timezone:
                raise ValueError(
                    "Comparison and selected periods must use the same timezone."
                )
            expected_to = self.period.date_from - timedelta(days=1)
            if (
                comparison.date_to != expected_to
                or comparison.day_count != self.period.day_count
            ):
                raise ValueError(
                    "comparison_period must be the immediately preceding "
                    "equal-length range."
                )
        latest_date = self.freshness.latest_transaction_date
        if latest_date is not None and not (
            self.period.date_from <= latest_date <= self.period.date_to
        ):
            raise ValueError(
                "latest_transaction_date must fall inside the selected period."
            )
        return self


class MoneyMetric(AnalyticsSchema):
    """Represent one exact four-decimal amount in the context currency."""

    value: MoneyValue

    @field_validator("value")
    @classmethod
    def normalize_money_scale(cls, value: Decimal) -> Decimal:
        """Serialize fresh and persisted financial amounts identically."""
        return value.quantize(_MONEY_QUANTUM)


class RateMetric(AnalyticsSchema):
    """Represent one six-decimal ratio; null means no valid denominator."""

    value: RatioValue | None

    @field_validator("value")
    @classmethod
    def normalize_rate_scale(cls, value: Decimal | None) -> Decimal | None:
        """Serialize ratios with the versioned six-decimal public scale."""
        return value.quantize(_RATIO_QUANTUM) if value is not None else None


class ShareMetric(RateMetric):
    """Represent a nullable bounded part-to-whole ratio."""

    @model_validator(mode="after")
    def validate_share(self) -> "ShareMetric":
        """Reject distribution shares outside the closed unit interval."""
        if self.value is not None and not Decimal("0") <= self.value <= Decimal(
            "1"
        ):
            raise ValueError("Distribution shares must be between zero and one.")
        return self


class CashFlowMetrics(AnalyticsSchema):
    """Headline metrics for one selected or comparison period."""

    gross_income: MoneyMetric
    total_expense: MoneyMetric
    net_cash_flow: MoneyMetric
    savings_amount: MoneyMetric
    savings_rate: RateMetric
    internal_transfer_volume: MoneyMetric
    net_adjustment: MoneyMetric

    @classmethod
    def from_aggregate(
        cls,
        aggregate: AnalyticsSummaryAggregate,
    ) -> "CashFlowMetrics":
        """Map exact internal totals to stable public metric wrappers."""
        return cls(
            gross_income=MoneyMetric(value=aggregate.gross_income),
            total_expense=MoneyMetric(value=aggregate.total_expense),
            net_cash_flow=MoneyMetric(value=aggregate.net_cash_flow),
            savings_amount=MoneyMetric(value=aggregate.savings_amount),
            savings_rate=RateMetric(value=aggregate.savings_rate),
            internal_transfer_volume=MoneyMetric(
                value=aggregate.internal_transfer_volume
            ),
            net_adjustment=MoneyMetric(value=aggregate.net_adjustment),
        )


class CashFlowPoint(AnalyticsSchema):
    """One observed calendar bucket in a cash-flow series."""

    period_start: date
    gross_income: MoneyMetric
    total_expense: MoneyMetric
    net_cash_flow: MoneyMetric
    transaction_count: int = Field(ge=1)

    @classmethod
    def from_aggregate(
        cls,
        aggregate: CashFlowBucketAggregate,
    ) -> "CashFlowPoint":
        """Map one exact internal bucket to its public representation."""
        return cls(
            period_start=aggregate.period_start,
            gross_income=MoneyMetric(value=aggregate.gross_income),
            total_expense=MoneyMetric(value=aggregate.total_expense),
            net_cash_flow=MoneyMetric(value=aggregate.net_cash_flow),
            transaction_count=aggregate.transaction_count,
        )


class CashFlowAnalyticsResponse(AnalyticsSchema):
    """Authenticated cash-flow totals, trend, and optional prior values."""

    context: AnalyticsContext
    granularity: AnalyticsGranularity
    metrics: CashFlowMetrics
    previous_period: CashFlowMetrics | None
    series: tuple[CashFlowPoint, ...]


class SpendingCategory(AnalyticsSchema):
    """One compatible canonical expense-category allocation."""

    category_id: UUID
    parent_category_id: UUID | None
    name: str = Field(min_length=1, max_length=100)
    classification_code: str | None = Field(default=None, max_length=64)
    kind: Literal[CategoryKind.EXPENSE] = CategoryKind.EXPENSE
    amount: MoneyMetric
    share: ShareMetric
    transaction_count: int = Field(ge=1)

    @classmethod
    def from_aggregate(
        cls,
        aggregate: CategoryAggregate,
        *,
        share: Decimal | None,
    ) -> "SpendingCategory":
        """Map one expense-category amount and its total-expense share."""
        if aggregate.kind is not CategoryKind.EXPENSE:
            raise ValueError("Spending categories must use expense kind.")
        return cls(
            category_id=aggregate.category_id,
            parent_category_id=aggregate.parent_category_id,
            name=aggregate.name,
            classification_code=aggregate.classification_code,
            amount=MoneyMetric(value=aggregate.amount),
            share=ShareMetric(value=share),
            transaction_count=aggregate.transaction_count,
        )


class SpendingMerchant(AnalyticsSchema):
    """One normalized merchant's eligible expense allocation."""

    normalized_merchant: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    amount: MoneyMetric
    share: ShareMetric
    transaction_count: int = Field(ge=1)

    @classmethod
    def from_aggregate(
        cls,
        aggregate: MerchantAggregate,
        *,
        share: Decimal | None,
    ) -> "SpendingMerchant":
        """Map one expense-only merchant allocation."""
        return cls(
            normalized_merchant=aggregate.normalized_merchant,
            display_name=aggregate.display_name,
            amount=MoneyMetric(value=aggregate.total_expense),
            share=ShareMetric(value=share),
            transaction_count=aggregate.expense_transaction_count,
        )


class SpendingAccount(AnalyticsSchema):
    """One owned historical account's eligible expense allocation."""

    account_id: UUID
    name: str = Field(min_length=1, max_length=120)
    account_type: AccountType
    amount: MoneyMetric
    share: ShareMetric
    transaction_count: int = Field(ge=1)

    @classmethod
    def from_aggregate(
        cls,
        aggregate: AccountAggregate,
        *,
        share: Decimal | None,
    ) -> "SpendingAccount":
        """Map one expense-only account allocation."""
        return cls(
            account_id=aggregate.account_id,
            name=aggregate.name,
            account_type=aggregate.account_type,
            amount=MoneyMetric(value=aggregate.total_expense),
            share=ShareMetric(value=share),
            transaction_count=aggregate.expense_transaction_count,
        )


class SpendingAnalyticsResponse(AnalyticsSchema):
    """Authenticated expense total and bounded dimension distributions."""

    context: AnalyticsContext
    total_expense: MoneyMetric
    previous_period_total_expense: MoneyMetric | None
    categories: tuple[SpendingCategory, ...]
    merchants: tuple[SpendingMerchant, ...]
    accounts: tuple[SpendingAccount, ...]


class RecurringPatternResponse(AnalyticsSchema):
    """One detected or explicitly abstained recurring candidate."""

    pattern_type: RecurringPatternType
    transaction_type: TransactionType
    normalized_merchant: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    classification_code: str | None = Field(default=None, max_length=64)
    category_name: str | None = Field(default=None, max_length=100)
    cadence: RecurringCadence
    decision: RecurringDecision
    confidence: RateMetric
    confidence_band: RecurringConfidenceBand
    reason_codes: tuple[RecurringReasonCode, ...]
    occurrence_count: int = Field(ge=MIN_RECURRING_OCCURRENCES)
    first_observed_date: date
    last_observed_date: date
    median_interval_days: Decimal = Field(ge=0, decimal_places=2)
    median_amount: MoneyMetric
    minimum_amount: MoneyMetric
    maximum_amount: MoneyMetric
    observed_total: MoneyMetric
    explanation: str = Field(min_length=1, max_length=200)

    @classmethod
    def from_pattern(
        cls,
        pattern: RecurringPattern,
    ) -> "RecurringPatternResponse":
        """Map deterministic evidence without exposing source transactions."""
        return cls(
            pattern_type=pattern.pattern_type,
            transaction_type=pattern.transaction_type,
            normalized_merchant=pattern.normalized_merchant,
            display_name=pattern.display_name,
            classification_code=pattern.classification_code,
            category_name=pattern.category_name,
            cadence=pattern.cadence,
            decision=pattern.decision,
            confidence=RateMetric(value=pattern.confidence),
            confidence_band=pattern.confidence_band,
            reason_codes=pattern.reason_codes,
            occurrence_count=pattern.occurrence_count,
            first_observed_date=pattern.first_observed_date,
            last_observed_date=pattern.last_observed_date,
            median_interval_days=pattern.median_interval_days,
            median_amount=MoneyMetric(value=pattern.median_amount),
            minimum_amount=MoneyMetric(value=pattern.minimum_amount),
            maximum_amount=MoneyMetric(value=pattern.maximum_amount),
            observed_total=MoneyMetric(value=pattern.observed_total),
            explanation=pattern.explanation,
        )

    @model_validator(mode="after")
    def validate_observed_evidence(self) -> "RecurringPatternResponse":
        """Reject inconsistent server-generated recurrence evidence."""
        if self.transaction_type not in {
            TransactionType.INCOME,
            TransactionType.EXPENSE,
        }:
            raise ValueError("Recurring patterns support income or expense only.")
        if self.last_observed_date < self.first_observed_date:
            raise ValueError("Recurring observation dates must be ordered.")
        if not (
            self.minimum_amount.value
            <= self.median_amount.value
            <= self.maximum_amount.value
        ):
            raise ValueError("Recurring amount bounds must contain the median.")
        if self.observed_total.value < self.maximum_amount.value:
            raise ValueError(
                "Recurring observed total cannot be below its maximum amount."
            )
        return self


class RecurringAnalyticsSummary(AnalyticsSchema):
    """Bounded totals describing recurrence detection output."""

    candidate_pattern_count: int = Field(ge=0)
    detected_pattern_count: int = Field(ge=0)
    abstained_pattern_count: int = Field(ge=0)
    returned_pattern_count: int = Field(ge=0)
    truncated: bool
    detected_income_observed: MoneyMetric
    detected_expense_observed: MoneyMetric

    @model_validator(mode="after")
    def validate_counts_and_amounts(self) -> "RecurringAnalyticsSummary":
        """Keep recurrence summary subsets and observed totals consistent."""
        if (
            self.detected_pattern_count + self.abstained_pattern_count
            != self.candidate_pattern_count
        ):
            raise ValueError(
                "Detected and abstained patterns must equal candidate patterns."
            )
        if self.returned_pattern_count > self.candidate_pattern_count:
            raise ValueError(
                "Returned patterns cannot exceed candidate patterns."
            )
        if (
            self.detected_income_observed.value < 0
            or self.detected_expense_observed.value < 0
        ):
            raise ValueError("Recurring observed totals cannot be negative.")
        return self


class RecurringAnalyticsResponse(AnalyticsSchema):
    """Owner-scoped recurring intelligence with explicit abstention."""

    context: AnalyticsContext
    policy_version: Literal["2026.1"] = RECURRING_POLICY_VERSION
    minimum_occurrences: int = Field(
        ge=MIN_RECURRING_OCCURRENCES,
        le=MAX_RECURRING_OCCURRENCES,
    )
    summary: RecurringAnalyticsSummary
    patterns: tuple[RecurringPatternResponse, ...]


class SpendingSignalEvaluationResponse(AnalyticsSchema):
    """Public status for one fixed leak or anomaly check."""

    signal_type: SpendingSignalType
    status: SpendingSignalEvaluationStatus
    source_observation_count: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=200)

    @classmethod
    def from_evaluation(
        cls,
        evaluation: SpendingSignalEvaluation,
    ) -> "SpendingSignalEvaluationResponse":
        return cls(
            signal_type=evaluation.signal_type,
            status=evaluation.status,
            source_observation_count=evaluation.source_observation_count,
            explanation=evaluation.explanation,
        )


class SpendingSignalResponse(AnalyticsSchema):
    """One bounded observation without source transaction identifiers."""

    signal_type: SpendingSignalType
    family: SpendingSignalFamily
    severity: SpendingSignalSeverity
    evidence_score: RateMetric
    reason_codes: tuple[SpendingSignalReasonCode, ...]
    observed_amount: MoneyMetric
    baseline_amount: MoneyMetric | None
    excess_amount: MoneyMetric | None
    share_of_total_expense: ShareMetric
    occurrence_count: int = Field(ge=1)
    first_observed_date: date
    last_observed_date: date
    normalized_merchant: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    classification_code: str | None = Field(default=None, max_length=64)
    category_name: str | None = Field(default=None, max_length=100)
    explanation: str = Field(min_length=1, max_length=240)

    @classmethod
    def from_signal(cls, signal: SpendingSignal) -> "SpendingSignalResponse":
        return cls(
            signal_type=signal.signal_type,
            family=signal.family,
            severity=signal.severity,
            evidence_score=RateMetric(value=signal.evidence_score),
            reason_codes=signal.reason_codes,
            observed_amount=MoneyMetric(value=signal.observed_amount),
            baseline_amount=(
                MoneyMetric(value=signal.baseline_amount)
                if signal.baseline_amount is not None
                else None
            ),
            excess_amount=(
                MoneyMetric(value=signal.excess_amount)
                if signal.excess_amount is not None
                else None
            ),
            share_of_total_expense=ShareMetric(
                value=signal.share_of_total_expense
            ),
            occurrence_count=signal.occurrence_count,
            first_observed_date=signal.first_observed_date,
            last_observed_date=signal.last_observed_date,
            normalized_merchant=signal.normalized_merchant,
            display_name=signal.display_name,
            classification_code=signal.classification_code,
            category_name=signal.category_name,
            explanation=signal.explanation,
        )

    @model_validator(mode="after")
    def validate_signal_evidence(self) -> "SpendingSignalResponse":
        if self.last_observed_date < self.first_observed_date:
            raise ValueError("Spending-signal observation dates must be ordered.")
        if self.observed_amount.value <= 0:
            raise ValueError("Spending-signal observed amount must be positive.")
        if self.baseline_amount is not None and self.baseline_amount.value < 0:
            raise ValueError("Spending-signal baseline cannot be negative.")
        if self.excess_amount is not None and self.excess_amount.value < 0:
            raise ValueError("Spending-signal excess cannot be negative.")
        return self


class SpendingSignalAnalyticsSummary(AnalyticsSchema):
    """Counts that do not double-count overlapping monetary evidence."""

    evaluated_transaction_count: int = Field(ge=0)
    detected_signal_count: int = Field(ge=0)
    potential_leak_signal_count: int = Field(ge=0)
    anomaly_signal_count: int = Field(ge=0)
    returned_signal_count: int = Field(ge=0)
    truncated: bool

    @model_validator(mode="after")
    def validate_signal_counts(self) -> "SpendingSignalAnalyticsSummary":
        if (
            self.potential_leak_signal_count + self.anomaly_signal_count
            != self.detected_signal_count
        ):
            raise ValueError(
                "Leak and anomaly signal counts must equal detected signals."
            )
        if self.returned_signal_count > self.detected_signal_count:
            raise ValueError("Returned signals cannot exceed detected signals.")
        return self


class SpendingSignalAnalyticsResponse(AnalyticsSchema):
    """Owner-scoped leak and anomaly evidence with explicit evaluation states."""

    context: AnalyticsContext
    policy_version: Literal["2026.1"] = SPENDING_SIGNAL_POLICY_VERSION
    summary: SpendingSignalAnalyticsSummary
    evaluations: tuple[SpendingSignalEvaluationResponse, ...]
    signals: tuple[SpendingSignalResponse, ...]

    @model_validator(mode="after")
    def validate_evaluation_coverage(self) -> "SpendingSignalAnalyticsResponse":
        evaluated = {item.signal_type for item in self.evaluations}
        if evaluated != set(SpendingSignalType):
            raise ValueError("Every spending-signal policy check must be evaluated.")
        if len(evaluated) != len(self.evaluations):
            raise ValueError("Spending-signal evaluations must be unique.")
        if len(self.signals) != self.summary.returned_signal_count:
            raise ValueError("Returned signal count must match the response list.")
        return self


class BudgetDescriptor(AnalyticsSchema):
    """Stored budget identity and period without exposing its owner."""

    budget_id: UUID
    name: str = Field(min_length=1, max_length=120)
    currency: CurrencyCode
    period_start_date: date
    period_end_date: date
    archived: bool

    @model_validator(mode="after")
    def validate_budget_period(self) -> "BudgetDescriptor":
        if self.period_end_date < self.period_start_date:
            raise ValueError("Budget period dates must be ordered.")
        return self


class BudgetPerformanceResponse(AnalyticsSchema):
    """Current usage plus transparent straight-line pace arithmetic."""

    limit_amount: MoneyMetric | None
    spent_amount: MoneyMetric
    remaining_allowance: MoneyMetric | None
    utilization_ratio: RateMetric
    period_progress_ratio: RateMetric
    elapsed_days: int = Field(ge=1, le=MAX_ANALYTICS_RANGE_DAYS)
    remaining_days: int = Field(ge=0, le=MAX_ANALYTICS_RANGE_DAYS)
    daily_burn_rate: MoneyMetric
    expected_spend_to_date: MoneyMetric | None
    pace_variance: MoneyMetric | None
    pace_projected_spend: MoneyMetric | None
    projected_variance: MoneyMetric | None
    projected_overspend_amount: MoneyMetric | None
    risk_level: BudgetRiskLevel
    warning_status: BudgetWarningStatus

    @classmethod
    def from_performance(
        cls,
        performance: BudgetPerformance,
    ) -> "BudgetPerformanceResponse":
        return cls(
            limit_amount=_optional_money(performance.limit_amount),
            spent_amount=MoneyMetric(value=performance.spent_amount),
            remaining_allowance=_optional_money(
                performance.remaining_allowance
            ),
            utilization_ratio=RateMetric(
                value=performance.utilization_ratio
            ),
            period_progress_ratio=RateMetric(
                value=performance.period_progress_ratio
            ),
            elapsed_days=performance.elapsed_days,
            remaining_days=performance.remaining_days,
            daily_burn_rate=MoneyMetric(value=performance.daily_burn_rate),
            expected_spend_to_date=_optional_money(
                performance.expected_spend_to_date
            ),
            pace_variance=_optional_money(performance.pace_variance),
            pace_projected_spend=_optional_money(
                performance.pace_projected_spend
            ),
            projected_variance=_optional_money(
                performance.projected_variance
            ),
            projected_overspend_amount=_optional_money(
                performance.projected_overspend_amount
            ),
            risk_level=performance.risk_level,
            warning_status=performance.warning_status,
        )

    @model_validator(mode="after")
    def validate_limit_relationships(self) -> "BudgetPerformanceResponse":
        if self.spent_amount.value < 0 or self.daily_burn_rate.value < 0:
            raise ValueError("Budget spending and burn rate cannot be negative.")
        if self.elapsed_days + self.remaining_days < 1:
            raise ValueError("Budget progress must contain at least one day.")
        progress = self.period_progress_ratio.value
        if progress is None or not Decimal("0") < progress <= Decimal("1"):
            raise ValueError("Budget period progress must be inside (0, 1].")
        limited_values = (
            self.remaining_allowance,
            self.utilization_ratio.value,
            self.expected_spend_to_date,
            self.pace_variance,
            self.pace_projected_spend,
            self.projected_variance,
            self.projected_overspend_amount,
        )
        if self.limit_amount is None:
            if any(value is not None for value in limited_values):
                raise ValueError(
                    "Limit-dependent budget metrics require a stored limit."
                )
            if (
                self.risk_level is not BudgetRiskLevel.UNAVAILABLE
                or self.warning_status is not BudgetWarningStatus.UNAVAILABLE
            ):
                raise ValueError("A missing limit requires unavailable risk.")
        elif (
            self.limit_amount.value <= 0
            or any(value is None for value in limited_values)
            or self.risk_level is BudgetRiskLevel.UNAVAILABLE
            or self.warning_status is BudgetWarningStatus.UNAVAILABLE
        ):
            raise ValueError(
                "A positive limit requires complete budget performance metrics."
            )
        return self


class BudgetCategoryPerformanceResponse(AnalyticsSchema):
    """Canonical category-limit performance within one budget."""

    category_id: UUID
    name: str = Field(min_length=1, max_length=100)
    classification_code: str | None = Field(default=None, max_length=64)
    transaction_count: int = Field(ge=0)
    performance: BudgetPerformanceResponse

    @classmethod
    def from_category(
        cls,
        category: BudgetCategoryPerformance,
    ) -> "BudgetCategoryPerformanceResponse":
        return cls(
            category_id=category.category_id,
            name=category.name,
            classification_code=category.classification_code,
            transaction_count=category.transaction_count,
            performance=BudgetPerformanceResponse.from_performance(
                category.performance
            ),
        )


class BudgetAnalyticsResponse(AnalyticsSchema):
    """Owner-scoped budget variance and bounded overspend-risk response."""

    context: AnalyticsContext
    policy_version: Literal["2026.1"] = BUDGET_POLICY_VERSION
    budget: BudgetDescriptor
    status: BudgetAnalysisStatus
    observed_to: date
    overall: BudgetPerformanceResponse
    configured_category_spend: MoneyMetric
    outside_configured_categories: MoneyMetric
    categories: tuple[BudgetCategoryPerformanceResponse, ...]

    @classmethod
    def from_analysis(
        cls,
        *,
        context: AnalyticsContext,
        definition: BudgetDefinition,
        analysis: BudgetAnalysis,
    ) -> "BudgetAnalyticsResponse":
        return cls(
            context=context,
            budget=BudgetDescriptor(
                budget_id=definition.budget_id,
                name=definition.name,
                currency=definition.currency,
                period_start_date=definition.period_start_date,
                period_end_date=definition.period_end_date,
                archived=definition.archived_at is not None,
            ),
            status=analysis.status,
            observed_to=analysis.observed_to,
            overall=BudgetPerformanceResponse.from_performance(
                analysis.overall
            ),
            configured_category_spend=MoneyMetric(
                value=analysis.configured_category_spend
            ),
            outside_configured_categories=MoneyMetric(
                value=analysis.outside_configured_categories
            ),
            categories=tuple(
                BudgetCategoryPerformanceResponse.from_category(item)
                for item in analysis.categories
            ),
        )

    @model_validator(mode="after")
    def validate_budget_context(self) -> "BudgetAnalyticsResponse":
        if self.context.currency != self.budget.currency:
            raise ValueError("Budget and analytics context currencies must match.")
        if self.context.period.date_from != self.budget.period_start_date:
            raise ValueError("Budget analytics must begin at the budget start.")
        if self.context.period.date_to != self.observed_to:
            raise ValueError("Budget observed_to must match the context period.")
        if (
            self.configured_category_spend.value
            + self.outside_configured_categories.value
            != self.overall.spent_amount.value
        ):
            raise ValueError(
                "Configured and outside-category spending must equal total usage."
            )
        return self


class FinancialHealthFactorResponse(AnalyticsSchema):
    """One factor's evidence, configured weight, and effective contribution."""

    factor: FinancialHealthFactor
    configured_weight: Decimal = Field(ge=0, le=100, decimal_places=2)
    status: FinancialHealthFactorStatus
    factor_score: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        decimal_places=2,
    )
    observed_value: Decimal | None = Field(default=None, decimal_places=6)
    benchmark_value: Decimal | None = Field(default=None, decimal_places=6)
    effective_weight: Decimal = Field(ge=0, le=100, decimal_places=2)
    contribution_points: Decimal = Field(ge=0, le=100, decimal_places=2)
    reason_codes: tuple[FinancialHealthReasonCode, ...] = Field(min_length=1)
    explanation: str = Field(min_length=1, max_length=240)

    @classmethod
    def from_result(
        cls,
        result: FinancialHealthFactorResult,
    ) -> "FinancialHealthFactorResponse":
        return cls(
            factor=result.factor,
            configured_weight=result.configured_weight,
            status=result.status,
            factor_score=result.factor_score,
            observed_value=result.observed_value,
            benchmark_value=result.benchmark_value,
            effective_weight=result.effective_weight,
            contribution_points=result.contribution_points,
            reason_codes=result.reason_codes,
            explanation=result.explanation,
        )

    @model_validator(mode="after")
    def validate_availability(self) -> "FinancialHealthFactorResponse":
        if self.status is FinancialHealthFactorStatus.UNAVAILABLE:
            if (
                self.factor_score is not None
                or self.observed_value is not None
                or self.benchmark_value is not None
                or self.effective_weight != 0
                or self.contribution_points != 0
            ):
                raise ValueError(
                    "Unavailable health factors cannot contribute to the score."
                )
        elif (
            self.factor_score is None
            or self.observed_value is None
            or self.benchmark_value is None
        ):
            raise ValueError("Available health factors require complete evidence.")
        return self


class FinancialHealthScoreResponse(AnalyticsSchema):
    """Versioned explainable financial-health planning indicator."""

    context: AnalyticsContext
    policy_version: Literal["2026.1"] = FINANCIAL_HEALTH_POLICY_VERSION
    status: FinancialHealthScoreStatus
    score: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    available_weight: Decimal = Field(ge=0, le=100, decimal_places=2)
    factors: tuple[FinancialHealthFactorResponse, ...]
    explanation: str = Field(min_length=1, max_length=240)

    @classmethod
    def from_analysis(
        cls,
        *,
        context: AnalyticsContext,
        analysis: FinancialHealthAnalysis,
    ) -> "FinancialHealthScoreResponse":
        return cls(
            context=context,
            status=analysis.status,
            score=analysis.score,
            available_weight=analysis.available_weight,
            factors=tuple(
                FinancialHealthFactorResponse.from_result(item)
                for item in analysis.factors
            ),
            explanation=analysis.explanation,
        )

    @model_validator(mode="after")
    def validate_score_composition(self) -> "FinancialHealthScoreResponse":
        expected_factors = tuple(FinancialHealthFactor)
        if tuple(item.factor for item in self.factors) != expected_factors:
            raise ValueError("Health-score factors must use the stable policy order.")
        configured_total = sum(
            (item.configured_weight for item in self.factors), Decimal("0")
        )
        if configured_total != Decimal("100"):
            raise ValueError("Configured health-score weights must total 100.")
        available_total = sum(
            (
                item.configured_weight
                for item in self.factors
                if item.status is FinancialHealthFactorStatus.AVAILABLE
            ),
            Decimal("0"),
        )
        if available_total != self.available_weight:
            raise ValueError(
                "available_weight must equal the available configured weights."
            )
        if self.status is FinancialHealthScoreStatus.UNAVAILABLE:
            if self.score is not None:
                raise ValueError("An unavailable health score must be null.")
            if any(
                item.effective_weight != 0 or item.contribution_points != 0
                for item in self.factors
            ):
                raise ValueError("An unavailable score cannot have contributions.")
            return self
        if self.score is None:
            raise ValueError("An available health score cannot be null.")
        if (
            self.status is FinancialHealthScoreStatus.COMPLETE
            and self.available_weight != Decimal("100")
        ) or (
            self.status is FinancialHealthScoreStatus.PARTIAL
            and self.available_weight >= Decimal("100")
        ):
            raise ValueError("Health-score status must match evidence availability.")
        contribution_total = sum(
            (item.contribution_points for item in self.factors), Decimal("0")
        )
        if contribution_total != self.score:
            raise ValueError("Factor contributions must equal the composite score.")
        effective_total = sum(
            (item.effective_weight for item in self.factors), Decimal("0")
        )
        if not Decimal("99.98") <= effective_total <= Decimal("100.02"):
            raise ValueError("Effective health-score weights must total 100.")
        return self


class PersonalFinanceInsightResponse(AnalyticsSchema):
    """One active recommendation with bounded evidence and no source IDs."""

    insight_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    insight_type: InsightType
    category: InsightCategory
    severity: InsightSeverity
    urgency: InsightUrgency
    confidence: InsightConfidence
    confidence_score: RateMetric
    priority_score: Decimal = Field(ge=0, le=100, decimal_places=2)
    lifecycle_state: InsightLifecycleState
    reason_codes: tuple[InsightReasonCode, ...] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=240)
    recommended_action: str = Field(min_length=1, max_length=240)
    estimated_period_impact: MoneyMetric | None
    impact_basis: InsightImpactBasis | None
    normalized_merchant: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    classification_code: str | None = Field(default=None, max_length=64)
    category_name: str | None = Field(default=None, max_length=100)

    @classmethod
    def from_insight(
        cls,
        insight: PersonalFinanceInsight,
    ) -> "PersonalFinanceInsightResponse":
        return cls(
            insight_id=insight.insight_id,
            insight_type=insight.insight_type,
            category=insight.category,
            severity=insight.severity,
            urgency=insight.urgency,
            confidence=insight.confidence,
            confidence_score=RateMetric(value=insight.confidence_score),
            priority_score=insight.priority_score,
            lifecycle_state=insight.lifecycle_state,
            reason_codes=insight.reason_codes,
            title=insight.title,
            explanation=insight.explanation,
            recommended_action=insight.recommended_action,
            estimated_period_impact=(
                MoneyMetric(value=insight.estimated_period_impact)
                if insight.estimated_period_impact is not None
                else None
            ),
            impact_basis=insight.impact_basis,
            normalized_merchant=insight.normalized_merchant,
            display_name=insight.display_name,
            classification_code=insight.classification_code,
            category_name=insight.category_name,
        )

    @model_validator(mode="after")
    def validate_impact(self) -> "PersonalFinanceInsightResponse":
        if (self.estimated_period_impact is None) != (self.impact_basis is None):
            raise ValueError("Insight impact and its basis must appear together.")
        if (
            self.estimated_period_impact is not None
            and self.estimated_period_impact.value < 0
        ):
            raise ValueError("Insight impact cannot be negative.")
        return self


class InsightAnalyticsSummary(AnalyticsSchema):
    """Bounded counts for the live prioritized insight set."""

    candidate_count: int = Field(ge=0)
    active_insight_count: int = Field(ge=0)
    high_severity_count: int = Field(ge=0)
    medium_severity_count: int = Field(ge=0)
    low_severity_count: int = Field(ge=0)
    returned_insight_count: int = Field(ge=0)
    truncated: bool

    @model_validator(mode="after")
    def validate_counts(self) -> "InsightAnalyticsSummary":
        if (
            self.high_severity_count
            + self.medium_severity_count
            + self.low_severity_count
            != self.active_insight_count
        ):
            raise ValueError("Severity counts must equal active insight count.")
        if self.returned_insight_count > self.active_insight_count:
            raise ValueError("Returned insight count cannot exceed active insights.")
        if self.active_insight_count > self.candidate_count:
            raise ValueError("Active insight count cannot exceed candidates.")
        if self.truncated != (
            self.returned_insight_count < self.active_insight_count
        ):
            raise ValueError("Insight truncation must match returned counts.")
        return self


class InsightAnalyticsResponse(AnalyticsSchema):
    """Owner-scoped deterministic recommendations ordered by priority."""

    context: AnalyticsContext
    policy_version: Literal["2026.1"] = INSIGHT_POLICY_VERSION
    status: InsightAnalysisStatus
    summary: InsightAnalyticsSummary
    insights: tuple[PersonalFinanceInsightResponse, ...]
    explanation: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_insight_set(self) -> "InsightAnalyticsResponse":
        if len(self.insights) != self.summary.returned_insight_count:
            raise ValueError("Returned insight count must match the response list.")
        identifiers = tuple(item.insight_id for item in self.insights)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Returned insights must be deduplicated.")
        ordering = tuple(
            (-item.priority_score, item.insight_id) for item in self.insights
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError("Insights must use stable descending priority order.")
        if self.status is InsightAnalysisStatus.AVAILABLE and not self.insights:
            raise ValueError("Available insight responses require an active insight.")
        if self.status is not InsightAnalysisStatus.AVAILABLE and self.insights:
            raise ValueError("Unavailable insight responses cannot return insights.")
        return self


def _optional_money(value: Decimal | None) -> MoneyMetric | None:
    return MoneyMetric(value=value) if value is not None else None


def _validate_date_range(
    date_from: date | None,
    date_to: date | None,
) -> int | None:
    if (date_from is None) != (date_to is None):
        raise ValueError("date_from and date_to must be supplied together.")
    if date_from is None or date_to is None:
        return None
    if date_to < date_from:
        raise ValueError("date_to must not be earlier than date_from.")
    day_count = (date_to - date_from).days + 1
    if day_count > MAX_ANALYTICS_RANGE_DAYS:
        raise ValueError(
            f"Analytics ranges cannot exceed {MAX_ANALYTICS_RANGE_DAYS} days."
        )
    return day_count
