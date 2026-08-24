"""Stable definitions shared by every Phase 8 analytics consumer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from enum import StrEnum
from types import MappingProxyType

from falcon_api.models.enums import TransactionStatus, TransactionType


ANALYTICS_CONTRACT_VERSION = "2026.1"
MAX_ANALYTICS_RANGE_DAYS = 366
RATIO_QUANTUM = Decimal("0.000001")


class AnalyticsMetricCode(StrEnum):
    """Stable identifiers for the first analytics contract."""

    GROSS_INCOME = "gross_income"
    TOTAL_EXPENSE = "total_expense"
    NET_CASH_FLOW = "net_cash_flow"
    SAVINGS_AMOUNT = "savings_amount"
    SAVINGS_RATE = "savings_rate"
    INTERNAL_TRANSFER_VOLUME = "internal_transfer_volume"
    NET_ADJUSTMENT = "net_adjustment"
    CLASSIFICATION_COVERAGE = "classification_coverage"


class AnalyticsCategoryState(StrEnum):
    """Explain how a transaction obtained its canonical category."""

    USER_CONFIRMED = "user_confirmed"
    AUTOMATIC = "automatic"
    USER_PROVIDED = "user_provided"
    SUGGESTED = "suggested"
    ABSTAINED = "abstained"
    UNCLASSIFIED = "unclassified"


class AnalyticsComparisonMode(StrEnum):
    """Supported comparison behavior for bounded analytics windows."""

    NONE = "none"
    PREVIOUS_PERIOD = "previous_period"


class AnalyticsConfidenceLevel(StrEnum):
    """Non-probabilistic confidence in data coverage for an analysis."""

    UNAVAILABLE = "unavailable"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnalyticsErrorCode(StrEnum):
    """Stable application error codes reserved by the analytics boundary."""

    DATE_IN_FUTURE = "analytics_date_in_future"
    INVALID_TRUSTED_TIMEZONE = "invalid_trusted_timezone"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """Machine-readable meaning of one versioned financial metric."""

    code: AnalyticsMetricCode
    label: str
    unit: str
    formula: str
    transaction_types: frozenset[TransactionType]
    statuses: frozenset[TransactionStatus]
    category_required: bool
    zero_data_value: str
    description: str


_POSTED = frozenset({TransactionStatus.POSTED})
_INCOME = frozenset({TransactionType.INCOME})
_EXPENSE = frozenset({TransactionType.EXPENSE})
_CASH_FLOW = frozenset({TransactionType.INCOME, TransactionType.EXPENSE})
_TRANSFER = frozenset({TransactionType.TRANSFER})
_ADJUSTMENT = frozenset({TransactionType.ADJUSTMENT})

_METRIC_DEFINITIONS = {
    AnalyticsMetricCode.GROSS_INCOME: MetricDefinition(
        code=AnalyticsMetricCode.GROSS_INCOME,
        label="Gross income",
        unit="money",
        formula="sum(abs(amount)) for posted income entries",
        transaction_types=_INCOME,
        statuses=_POSTED,
        category_required=False,
        zero_data_value="0.0000",
        description=(
            "All posted income magnitudes in the selected currency and inclusive "
            "date window; transfers, expenses, adjustments, and pending rows are "
            "excluded."
        ),
    ),
    AnalyticsMetricCode.TOTAL_EXPENSE: MetricDefinition(
        code=AnalyticsMetricCode.TOTAL_EXPENSE,
        label="Total expense",
        unit="money",
        formula="sum(abs(amount)) for posted expense entries",
        transaction_types=_EXPENSE,
        statuses=_POSTED,
        category_required=False,
        zero_data_value="0.0000",
        description=(
            "All posted expense magnitudes in the selected currency and inclusive "
            "date window, including investment-category outflows; transfers, "
            "adjustments, and pending rows are excluded."
        ),
    ),
    AnalyticsMetricCode.NET_CASH_FLOW: MetricDefinition(
        code=AnalyticsMetricCode.NET_CASH_FLOW,
        label="Net cash flow",
        unit="money",
        formula="gross_income - total_expense",
        transaction_types=_CASH_FLOW,
        statuses=_POSTED,
        category_required=False,
        zero_data_value="0.0000",
        description=(
            "Posted external inflows less posted external outflows. Internal "
            "transfers and accounting adjustments are excluded."
        ),
    ),
    AnalyticsMetricCode.SAVINGS_AMOUNT: MetricDefinition(
        code=AnalyticsMetricCode.SAVINGS_AMOUNT,
        label="Savings amount",
        unit="money",
        formula="gross_income - total_expense",
        transaction_types=_CASH_FLOW,
        statuses=_POSTED,
        category_required=False,
        zero_data_value="0.0000",
        description=(
            "A cash-flow savings proxy equal to net cash flow. It may be negative "
            "and is not account balance, net worth, or investment performance."
        ),
    ),
    AnalyticsMetricCode.SAVINGS_RATE: MetricDefinition(
        code=AnalyticsMetricCode.SAVINGS_RATE,
        label="Savings rate",
        unit="ratio",
        formula="savings_amount / gross_income when gross_income > 0",
        transaction_types=_CASH_FLOW,
        statuses=_POSTED,
        category_required=False,
        zero_data_value="null",
        description=(
            "The cash-flow savings proxy divided by gross income. It is null when "
            "gross income is zero and is returned as a ratio rather than a percent."
        ),
    ),
    AnalyticsMetricCode.INTERNAL_TRANSFER_VOLUME: MetricDefinition(
        code=AnalyticsMetricCode.INTERNAL_TRANSFER_VOLUME,
        label="Internal transfer volume",
        unit="money",
        formula="sum(abs(amount)) for one posted debit leg per transfer group",
        transaction_types=_TRANSFER,
        statuses=_POSTED,
        category_required=False,
        zero_data_value="0.0000",
        description=(
            "Money moved between the user's own same-currency accounts, counted "
            "once from each transfer group's negative leg and never as income or "
            "expense."
        ),
    ),
    AnalyticsMetricCode.NET_ADJUSTMENT: MetricDefinition(
        code=AnalyticsMetricCode.NET_ADJUSTMENT,
        label="Net adjustment",
        unit="money",
        formula="sum(amount) for posted adjustment entries",
        transaction_types=_ADJUSTMENT,
        statuses=_POSTED,
        category_required=False,
        zero_data_value="0.0000",
        description=(
            "Signed balance corrections reported separately from income, expense, "
            "cash flow, and savings."
        ),
    ),
    AnalyticsMetricCode.CLASSIFICATION_COVERAGE: MetricDefinition(
        code=AnalyticsMetricCode.CLASSIFICATION_COVERAGE,
        label="Classification coverage",
        unit="ratio",
        formula="categorized eligible income-and-expense count / eligible count",
        transaction_types=_CASH_FLOW,
        statuses=_POSTED,
        category_required=True,
        zero_data_value="null",
        description=(
            "Count-based coverage of canonical ledger categories. It is not an "
            "average model confidence and does not weight transactions by amount."
        ),
    ),
}

METRIC_DEFINITIONS = MappingProxyType(_METRIC_DEFINITIONS)


def metric_definition(code: AnalyticsMetricCode) -> MetricDefinition:
    """Return the immutable definition for one supported metric."""
    return METRIC_DEFINITIONS[code]


def classification_completeness(
    *,
    eligible_count: int,
    categorized_count: int,
) -> tuple[Decimal | None, AnalyticsConfidenceLevel]:
    """Calculate coverage and its deliberately non-probabilistic quality band."""
    if eligible_count < 0 or categorized_count < 0:
        raise ValueError("Analytics completeness counts cannot be negative.")
    if categorized_count > eligible_count:
        raise ValueError("Categorized count cannot exceed eligible count.")
    if eligible_count == 0:
        return None, AnalyticsConfidenceLevel.UNAVAILABLE

    coverage = (Decimal(categorized_count) / Decimal(eligible_count)).quantize(
        RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
    if eligible_count < 10 or coverage < Decimal("0.600000"):
        confidence = AnalyticsConfidenceLevel.LOW
    elif eligible_count < 30 or coverage < Decimal("0.900000"):
        confidence = AnalyticsConfidenceLevel.MEDIUM
    else:
        confidence = AnalyticsConfidenceLevel.HIGH
    return coverage, confidence
