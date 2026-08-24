"""Deterministic budget variance and bounded pace-risk policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from enum import StrEnum
from uuid import UUID

from falcon_api.analytics.semantics import (
    MAX_ANALYTICS_RANGE_DAYS,
    RATIO_QUANTUM,
)
from falcon_api.analytics.types import (
    BudgetCategorySpendingAggregate,
    BudgetDefinition,
    money,
)


BUDGET_POLICY_VERSION = "2026.1"
_HIGH_OVERRUN_RATIO = Decimal("1.100000")
_APPROACHING_UTILIZATION = Decimal("0.800000")


class BudgetAnalysisStatus(StrEnum):
    """Whether the stored budget is still in progress or complete."""

    ACTIVE = "active"
    COMPLETED = "completed"


class BudgetRiskLevel(StrEnum):
    """Non-probabilistic overspend evidence bands."""

    UNAVAILABLE = "unavailable"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BudgetWarningStatus(StrEnum):
    """Bounded current/pace states without prescribing an action."""

    UNAVAILABLE = "unavailable"
    WITHIN_BUDGET = "within_budget"
    APPROACHING_LIMIT = "approaching_limit"
    PROJECTED_OVERSPEND = "projected_overspend"
    OVER_LIMIT = "over_limit"


@dataclass(frozen=True, slots=True)
class BudgetPerformance:
    """Exact current usage and linear pace arithmetic for one limit."""

    limit_amount: Decimal | None
    spent_amount: Decimal
    remaining_allowance: Decimal | None
    utilization_ratio: Decimal | None
    period_progress_ratio: Decimal
    elapsed_days: int
    remaining_days: int
    daily_burn_rate: Decimal
    expected_spend_to_date: Decimal | None
    pace_variance: Decimal | None
    pace_projected_spend: Decimal | None
    projected_variance: Decimal | None
    projected_overspend_amount: Decimal | None
    risk_level: BudgetRiskLevel
    warning_status: BudgetWarningStatus


@dataclass(frozen=True, slots=True)
class BudgetCategoryPerformance:
    """One configured category limit and its canonical spending usage."""

    category_id: UUID
    name: str
    classification_code: str | None
    transaction_count: int
    performance: BudgetPerformance


@dataclass(frozen=True, slots=True)
class BudgetAnalysis:
    """Complete policy result before mapping to the public schema."""

    status: BudgetAnalysisStatus
    observed_to: date
    overall: BudgetPerformance
    categories: tuple[BudgetCategoryPerformance, ...]
    configured_category_spend: Decimal
    outside_configured_categories: Decimal


def evaluate_budget(
    definition: BudgetDefinition,
    category_spending: tuple[BudgetCategorySpendingAggregate, ...],
    *,
    total_expense: Decimal,
    local_today: date,
) -> BudgetAnalysis:
    """Calculate current usage and a transparent straight-line pace scenario."""
    if definition.period_start_date > local_today:
        raise ValueError("Budget analysis cannot begin before its start date.")
    total_days = (definition.period_end_date - definition.period_start_date).days + 1
    if total_days <= 0:
        raise ValueError("Budget period must contain at least one day.")
    if total_days > MAX_ANALYTICS_RANGE_DAYS:
        raise ValueError(
            f"Budget periods cannot exceed {MAX_ANALYTICS_RANGE_DAYS} days."
        )
    observed_to = min(local_today, definition.period_end_date)
    elapsed_days = (observed_to - definition.period_start_date).days + 1
    remaining_days = total_days - elapsed_days
    status = (
        BudgetAnalysisStatus.COMPLETED
        if observed_to == definition.period_end_date
        else BudgetAnalysisStatus.ACTIVE
    )
    normalized_total = money(total_expense)
    if normalized_total < 0:
        raise ValueError("Budget total expense cannot be negative.")

    spending_by_category = {item.category_id: item for item in category_spending}
    configured_ids = {item.category_id for item in definition.category_limits}
    if set(spending_by_category) - configured_ids:
        raise ValueError("Category spending must belong to a configured limit.")

    categories = []
    configured_spend = Decimal("0")
    for limit in definition.category_limits:
        aggregate = spending_by_category.get(limit.category_id)
        spent = aggregate.amount if aggregate is not None else Decimal("0")
        count = aggregate.transaction_count if aggregate is not None else 0
        configured_spend += spent
        categories.append(
            BudgetCategoryPerformance(
                category_id=limit.category_id,
                name=limit.name,
                classification_code=limit.classification_code,
                transaction_count=count,
                performance=_performance(
                    limit_amount=limit.limit_amount,
                    spent_amount=spent,
                    elapsed_days=elapsed_days,
                    remaining_days=remaining_days,
                    total_days=total_days,
                    status=status,
                ),
            )
        )
    configured_spend = money(configured_spend)
    if configured_spend > normalized_total:
        raise ValueError("Configured category spending cannot exceed total expense.")

    return BudgetAnalysis(
        status=status,
        observed_to=observed_to,
        overall=_performance(
            limit_amount=definition.overall_limit,
            spent_amount=normalized_total,
            elapsed_days=elapsed_days,
            remaining_days=remaining_days,
            total_days=total_days,
            status=status,
        ),
        categories=tuple(categories),
        configured_category_spend=configured_spend,
        outside_configured_categories=money(normalized_total - configured_spend),
    )


def _performance(
    *,
    limit_amount: Decimal | None,
    spent_amount: Decimal,
    elapsed_days: int,
    remaining_days: int,
    total_days: int,
    status: BudgetAnalysisStatus,
) -> BudgetPerformance:
    spent = money(spent_amount)
    daily_burn = money(spent / Decimal(elapsed_days))
    progress = _ratio(Decimal(elapsed_days), Decimal(total_days))
    if limit_amount is None:
        return BudgetPerformance(
            limit_amount=None,
            spent_amount=spent,
            remaining_allowance=None,
            utilization_ratio=None,
            period_progress_ratio=progress,
            elapsed_days=elapsed_days,
            remaining_days=remaining_days,
            daily_burn_rate=daily_burn,
            expected_spend_to_date=None,
            pace_variance=None,
            pace_projected_spend=None,
            projected_variance=None,
            projected_overspend_amount=None,
            risk_level=BudgetRiskLevel.UNAVAILABLE,
            warning_status=BudgetWarningStatus.UNAVAILABLE,
        )

    limit = money(limit_amount)
    if limit <= 0:
        raise ValueError("Budget limits must be positive.")
    remaining = money(limit - spent)
    utilization = _ratio(spent, limit)
    expected = money(limit * progress)
    pace_variance = money(expected - spent)
    projected = (
        spent
        if status is BudgetAnalysisStatus.COMPLETED
        else money(spent / Decimal(elapsed_days) * Decimal(total_days))
    )
    projected_variance = money(limit - projected)
    projected_overspend = money(max(Decimal("0"), projected - limit))
    risk, warning = _risk_and_warning(
        spent=spent,
        limit=limit,
        utilization=utilization,
        projected=projected,
        status=status,
    )
    return BudgetPerformance(
        limit_amount=limit,
        spent_amount=spent,
        remaining_allowance=remaining,
        utilization_ratio=utilization,
        period_progress_ratio=progress,
        elapsed_days=elapsed_days,
        remaining_days=remaining_days,
        daily_burn_rate=daily_burn,
        expected_spend_to_date=expected,
        pace_variance=pace_variance,
        pace_projected_spend=projected,
        projected_variance=projected_variance,
        projected_overspend_amount=projected_overspend,
        risk_level=risk,
        warning_status=warning,
    )


def _risk_and_warning(
    *,
    spent: Decimal,
    limit: Decimal,
    utilization: Decimal,
    projected: Decimal,
    status: BudgetAnalysisStatus,
) -> tuple[BudgetRiskLevel, BudgetWarningStatus]:
    if spent > limit:
        return BudgetRiskLevel.HIGH, BudgetWarningStatus.OVER_LIMIT
    if status is BudgetAnalysisStatus.COMPLETED:
        return BudgetRiskLevel.LOW, BudgetWarningStatus.WITHIN_BUDGET
    projected_ratio = _ratio(projected, limit)
    if projected_ratio >= _HIGH_OVERRUN_RATIO:
        return BudgetRiskLevel.HIGH, BudgetWarningStatus.PROJECTED_OVERSPEND
    if projected > limit:
        return BudgetRiskLevel.MEDIUM, BudgetWarningStatus.PROJECTED_OVERSPEND
    if utilization >= _APPROACHING_UTILIZATION:
        return BudgetRiskLevel.LOW, BudgetWarningStatus.APPROACHING_LIMIT
    return BudgetRiskLevel.LOW, BudgetWarningStatus.WITHIN_BUDGET


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(
        RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
