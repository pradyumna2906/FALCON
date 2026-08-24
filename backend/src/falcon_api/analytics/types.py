"""Exact internal result types for owner-scoped financial aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from enum import StrEnum
from uuid import UUID

from falcon_api.analytics.semantics import RATIO_QUANTUM
from falcon_api.models.enums import AccountType, CategoryKind, TransactionType


MONEY_QUANTUM = Decimal("0.0001")
MAX_ANALYTICS_DIMENSION_ROWS = 100


class AnalyticsGranularity(StrEnum):
    """Calendar bucket sizes supported by the aggregation foundation."""

    DAY = "day"
    MONTH = "month"


def money(value: Decimal | int) -> Decimal:
    """Normalize database numeric values to the analytics money scale."""
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class AnalyticsSummaryAggregate:
    """One exact live summary plus its completeness source counts."""

    gross_income: Decimal
    total_expense: Decimal
    internal_transfer_volume: Decimal
    net_adjustment: Decimal
    eligible_transaction_count: int
    categorized_transaction_count: int
    suggested_transaction_count: int
    abstained_transaction_count: int
    pending_count: int
    transfer_entry_count: int
    adjustment_count: int
    other_currency_count: int
    latest_transaction_date: date | None
    source_last_updated_at: datetime | None

    @property
    def net_cash_flow(self) -> Decimal:
        """Return income less expense without floating-point arithmetic."""
        return money(self.gross_income - self.total_expense)

    @property
    def savings_amount(self) -> Decimal:
        """Return the contract's cash-flow savings proxy."""
        return self.net_cash_flow

    @property
    def savings_rate(self) -> Decimal | None:
        """Return the six-decimal savings ratio when income is positive."""
        if self.gross_income <= 0:
            return None
        return (self.savings_amount / self.gross_income).quantize(
            RATIO_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )


@dataclass(frozen=True, slots=True)
class CashFlowBucketAggregate:
    """Income and expense totals for one observed calendar bucket."""

    period_start: date
    gross_income: Decimal
    total_expense: Decimal
    transaction_count: int

    @property
    def net_cash_flow(self) -> Decimal:
        """Return this bucket's exact external cash flow."""
        return money(self.gross_income - self.total_expense)


@dataclass(frozen=True, slots=True)
class CategoryAggregate:
    """Canonical category allocation for one compatible category."""

    category_id: UUID
    parent_category_id: UUID | None
    name: str
    classification_code: str | None
    kind: CategoryKind
    amount: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class MerchantAggregate:
    """Case-normalized merchant allocation, including an unattributed bucket."""

    normalized_merchant: str | None
    display_name: str | None
    gross_income: Decimal
    total_expense: Decimal
    transaction_count: int
    income_transaction_count: int
    expense_transaction_count: int


@dataclass(frozen=True, slots=True)
class AccountAggregate:
    """External cash-flow allocation for one owned historical account."""

    account_id: UUID
    name: str
    account_type: AccountType
    gross_income: Decimal
    total_expense: Decimal
    transaction_count: int
    income_transaction_count: int
    expense_transaction_count: int


@dataclass(frozen=True, slots=True)
class RecurringTransactionRecord:
    """One bounded ledger observation used for recurrence detection."""

    transaction_date: date
    transaction_type: TransactionType
    amount: Decimal
    normalized_merchant: str | None
    display_name: str | None
    classification_code: str | None
    category_name: str | None


@dataclass(frozen=True, slots=True)
class SpendingSignalTransactionRecord:
    """One private posted-expense observation used by signal policies."""

    transaction_date: date
    amount: Decimal
    normalized_merchant: str | None
    display_name: str | None
    classification_code: str | None
    category_name: str | None


@dataclass(frozen=True, slots=True)
class BudgetCategoryLimitDefinition:
    """One valid canonical expense-category limit in an owned budget."""

    category_id: UUID
    name: str
    classification_code: str | None
    limit_amount: Decimal


@dataclass(frozen=True, slots=True)
class BudgetDefinition:
    """One owner-scoped stored plan plus its immutable read-time limits."""

    budget_id: UUID
    name: str
    period_start_date: date
    period_end_date: date
    currency: str
    overall_limit: Decimal | None
    archived_at: datetime | None
    category_limits: tuple[BudgetCategoryLimitDefinition, ...]


@dataclass(frozen=True, slots=True)
class BudgetCategorySpendingAggregate:
    """Observed posted spending allocated to one configured category limit."""

    category_id: UUID
    amount: Decimal
    transaction_count: int
