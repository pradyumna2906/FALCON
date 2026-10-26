"""Debt-aware and emergency-fund-safe goal optimization guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from falcon_api.analytics.types import money
from falcon_api.goal_planning.ranking import GoalRanking
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningSnapshotWarning,
)
from falcon_api.models.enums import ProfileCompletionStatus


OPTIMIZATION_GUARDRAIL_POLICY_VERSION = "2026.1"
DEFAULT_EMERGENCY_FUND_TARGET_MONTHS = Decimal("3.0000")


class OptimizationGuardrailStatus(StrEnum):
    """Readiness of one immutable snapshot for automatic allocation."""

    READY = "ready"
    CAUTION = "caution"
    BLOCKED = "blocked"


class OptimizationGuardrailReasonCode(StrEnum):
    """Stable, public-safe explanations for a guardrail decision."""

    OPTIMIZATION_READY = "optimization_ready"
    PROTECTED_CAPACITY_MISSING = "protected_capacity_missing"
    PROTECTED_CAPACITY_EMPTY = "protected_capacity_empty"
    NO_ELIGIBLE_GOALS = "no_eligible_goals"
    DEBT_PAYMENT_EVIDENCE_INCOMPLETE = "debt_payment_evidence_incomplete"
    FORECAST_PROVISIONAL = "forecast_provisional"
    PROFILE_MISSING = "profile_missing"
    PROFILE_INCOMPLETE = "profile_incomplete"
    BUDGET_MISSING = "budget_missing"
    BUDGET_LIMIT_INCOMPLETE = "budget_limit_incomplete"
    EMERGENCY_BASELINE_UNAVAILABLE = "emergency_baseline_unavailable"
    EMERGENCY_RESERVE_REQUIRED = "emergency_reserve_required"
    MIXED_CURRENCY_GOALS_EXCLUDED = "mixed_currency_goals_excluded"
    SNAPSHOT_EVIDENCE_INCOMPLETE = "snapshot_evidence_incomplete"


@dataclass(frozen=True, slots=True)
class OptimizationGuardrailAssessment:
    """Exact evidence and reserve applied before solving an allocation plan."""

    policy_version: str
    snapshot_id: str
    status: OptimizationGuardrailStatus
    can_optimize: bool
    protected_capacity_total: Decimal
    liquid_balance_protected: Decimal
    outstanding_debt: Decimal
    monthly_debt_payment: Decimal
    debt_payment_evidence_complete: bool
    emergency_target_months: Decimal
    monthly_expense_baseline: Decimal | None
    emergency_target_amount: Decimal | None
    emergency_fund_gap: Decimal | None
    emergency_reserve_amount: Decimal
    reason_codes: tuple[OptimizationGuardrailReasonCode, ...]


def evaluate_optimization_guardrails(
    *,
    snapshot: GoalPlanningSnapshot,
    ranking: GoalRanking,
) -> OptimizationGuardrailAssessment:
    """Fail closed on unsafe inputs and reserve capacity for emergency needs."""
    if ranking.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Ranking and planning snapshot identifiers must match.")

    capacity = snapshot.savings_capacity
    protected_capacity = money(
        capacity.protected_total if capacity is not None else Decimal("0")
    )
    debt_complete = (
        snapshot.finances.liability_payment_count
        == snapshot.finances.liability_account_count
    )
    eligible_goal_count = sum(
        item.eligible_for_allocation for item in ranking.items
    )
    emergency_months = _emergency_target_months(snapshot)
    expense_baseline = _monthly_expense_baseline(snapshot)
    emergency_target = (
        money(expense_baseline * emergency_months)
        if expense_baseline is not None
        else None
    )
    liquid_balance = money(max(Decimal("0"), snapshot.finances.liquid_balance))
    emergency_gap = (
        money(max(Decimal("0"), emergency_target - liquid_balance))
        if emergency_target is not None
        else None
    )
    emergency_reserve = money(emergency_gap or Decimal("0"))

    blocking: list[OptimizationGuardrailReasonCode] = []
    caution: list[OptimizationGuardrailReasonCode] = []
    if capacity is None:
        blocking.append(
            OptimizationGuardrailReasonCode.PROTECTED_CAPACITY_MISSING
        )
    elif protected_capacity <= 0:
        blocking.append(OptimizationGuardrailReasonCode.PROTECTED_CAPACITY_EMPTY)
    if eligible_goal_count == 0:
        blocking.append(OptimizationGuardrailReasonCode.NO_ELIGIBLE_GOALS)
    if not debt_complete:
        blocking.append(
            OptimizationGuardrailReasonCode.DEBT_PAYMENT_EVIDENCE_INCOMPLETE
        )

    if capacity is not None and capacity.reliability == "provisional":
        caution.append(OptimizationGuardrailReasonCode.FORECAST_PROVISIONAL)
    if snapshot.profile is None:
        caution.append(OptimizationGuardrailReasonCode.PROFILE_MISSING)
    elif snapshot.profile.completion_status is not ProfileCompletionStatus.COMPLETE:
        caution.append(OptimizationGuardrailReasonCode.PROFILE_INCOMPLETE)
    if snapshot.budgets.active_budget_count == 0:
        caution.append(OptimizationGuardrailReasonCode.BUDGET_MISSING)
    elif (
        snapshot.budgets.budget_with_overall_limit_count
        < snapshot.budgets.active_budget_count
    ):
        caution.append(OptimizationGuardrailReasonCode.BUDGET_LIMIT_INCOMPLETE)
    if emergency_target is None:
        caution.append(
            OptimizationGuardrailReasonCode.EMERGENCY_BASELINE_UNAVAILABLE
        )
    elif emergency_reserve > 0:
        caution.append(
            OptimizationGuardrailReasonCode.EMERGENCY_RESERVE_REQUIRED
        )

    known_snapshot_warnings = {
        PlanningSnapshotWarning.NO_ACTIVE_GOALS,
        PlanningSnapshotWarning.PROFILE_MISSING,
        PlanningSnapshotWarning.PROFILE_INCOMPLETE,
        PlanningSnapshotWarning.BUDGET_MISSING,
        PlanningSnapshotWarning.DEBT_PAYMENT_INCOMPLETE,
        PlanningSnapshotWarning.SAVINGS_FORECAST_MISSING,
        PlanningSnapshotWarning.SAVINGS_FORECAST_PROVISIONAL,
        PlanningSnapshotWarning.SAVINGS_FORECAST_UNUSABLE,
        PlanningSnapshotWarning.MIXED_CURRENCY_GOALS_EXCLUDED,
    }
    if PlanningSnapshotWarning.MIXED_CURRENCY_GOALS_EXCLUDED in snapshot.warnings:
        caution.append(
            OptimizationGuardrailReasonCode.MIXED_CURRENCY_GOALS_EXCLUDED
        )
    if any(warning not in known_snapshot_warnings for warning in snapshot.warnings):
        caution.append(
            OptimizationGuardrailReasonCode.SNAPSHOT_EVIDENCE_INCOMPLETE
        )

    blocking = _deduplicate(blocking)
    caution = _deduplicate(caution)
    if blocking:
        status = OptimizationGuardrailStatus.BLOCKED
        reasons = (*blocking, *caution)
    elif caution:
        status = OptimizationGuardrailStatus.CAUTION
        reasons = tuple(caution)
    else:
        status = OptimizationGuardrailStatus.READY
        reasons = (OptimizationGuardrailReasonCode.OPTIMIZATION_READY,)

    return OptimizationGuardrailAssessment(
        policy_version=OPTIMIZATION_GUARDRAIL_POLICY_VERSION,
        snapshot_id=snapshot.snapshot_id,
        status=status,
        can_optimize=status is not OptimizationGuardrailStatus.BLOCKED,
        protected_capacity_total=protected_capacity,
        liquid_balance_protected=liquid_balance,
        outstanding_debt=money(snapshot.finances.outstanding_debt),
        monthly_debt_payment=money(snapshot.finances.monthly_debt_payment),
        debt_payment_evidence_complete=debt_complete,
        emergency_target_months=emergency_months,
        monthly_expense_baseline=expense_baseline,
        emergency_target_amount=emergency_target,
        emergency_fund_gap=emergency_gap,
        emergency_reserve_amount=emergency_reserve,
        reason_codes=reasons,
    )


def _emergency_target_months(snapshot: GoalPlanningSnapshot) -> Decimal:
    configured = (
        snapshot.profile.emergency_fund_target_months
        if snapshot.profile is not None
        else None
    )
    if configured is None or configured <= 0:
        return DEFAULT_EMERGENCY_FUND_TARGET_MONTHS
    return Decimal(configured).quantize(Decimal("0.0001"))


def _monthly_expense_baseline(
    snapshot: GoalPlanningSnapshot,
) -> Decimal | None:
    budgets = snapshot.budgets
    if budgets.budget_with_overall_limit_count == 0:
        return None
    if budgets.total_overall_limit <= 0:
        return None
    return money(budgets.total_overall_limit)


def _deduplicate(
    values: list[OptimizationGuardrailReasonCode],
) -> list[OptimizationGuardrailReasonCode]:
    return list(dict.fromkeys(values))
