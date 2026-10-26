"""Checkpoint 10.10 debt and emergency-fund guardrail tests."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.goal_planning import (
    DEFAULT_EMERGENCY_FUND_TARGET_MONTHS,
    OPTIMIZATION_GUARDRAIL_POLICY_VERSION,
    OptimizationGuardrailReasonCode,
    OptimizationGuardrailStatus,
    SavingsCapacityPlan,
    SavingsCapacityPoint,
    analyze_goal_planning_snapshot,
    calculate_goal_progress,
    evaluate_optimization_guardrails,
)
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningBudgetEvidence,
    PlanningFinancialEvidence,
    PlanningProfileEvidence,
    PlanningProvenance,
    PlanningSnapshotWarning,
)
from falcon_api.models.enums import (
    GoalPriority,
    GoalStatus,
    GoalType,
    ProfileCompletionStatus,
)
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def _snapshot(
    *,
    capacity: SavingsCapacityPlan | None = None,
    liquid_balance: str = "2000",
    liabilities: int = 0,
    liability_payments: int = 0,
    profile: PlanningProfileEvidence | None | bool = True,
    budget_count: int = 1,
    budget_limit_count: int = 1,
    budget_limit: str = "500",
    warnings: tuple[PlanningSnapshotWarning, ...] = (),
) -> GoalPlanningSnapshot:
    goal = Goal(
        id=uuid4(),
        user_id=uuid4(),
        name="Education",
        goal_type=GoalType.EDUCATION,
        target_amount=Decimal("1000"),
        starting_amount=Decimal("0"),
        currency="INR",
        target_date=date(2026, 12, 31),
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
        description=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    progress = calculate_goal_progress(
        goal=goal,
        contribution_amount=Decimal("0"),
        calculated_on=date(2026, 9, 15),
    )
    resolved_capacity = capacity if capacity is not None else _capacity()
    if profile is True:
        resolved_profile = PlanningProfileEvidence(
            completion_status=ProfileCompletionStatus.COMPLETE,
            income_stability="stable",
            emergency_fund_target_months=Decimal("3"),
            updated_at=_NOW,
        )
    else:
        resolved_profile = profile
    return GoalPlanningSnapshot(
        snapshot_id="a" * 64,
        contract_version="2026.1",
        cutoff_at=_NOW,
        local_date=date(2026, 9, 15),
        timezone="Asia/Kolkata",
        currency="INR",
        goals=(progress,),
        profile=resolved_profile,
        finances=PlanningFinancialEvidence(
            liquid_balance=Decimal(liquid_balance),
            liability_account_count=liabilities,
            liability_payment_count=liability_payments,
            outstanding_debt=Decimal("4000" if liabilities else "0"),
            monthly_debt_payment=Decimal("300" if liability_payments else "0"),
            source_last_updated_at=_NOW,
        ),
        budgets=PlanningBudgetEvidence(
            active_budget_count=budget_count,
            budget_with_overall_limit_count=budget_limit_count,
            total_overall_limit=Decimal(budget_limit),
            source_last_updated_at=_NOW if budget_count else None,
        ),
        savings_capacity=resolved_capacity,
        warnings=warnings,
        provenance=PlanningProvenance(
            goal_ids=(goal.id,),
            contribution_count=0,
            forecast_run_id=resolved_capacity.forecast_run_id,
            source_last_updated_at=_NOW,
        ),
    )


def _capacity(*, reliability: str = "normal") -> SavingsCapacityPlan:
    points = (
        SavingsCapacityPoint(
            period_start=date(2026, 10, 1),
            protected_amount=Decimal("600"),
            expected_amount=Decimal("800"),
            upside_amount=Decimal("1000"),
        ),
        SavingsCapacityPoint(
            period_start=date(2026, 11, 1),
            protected_amount=Decimal("600"),
            expected_amount=Decimal("800"),
            upside_amount=Decimal("1000"),
        ),
    )
    return SavingsCapacityPlan(
        forecast_run_id=uuid4(),
        currency="INR",
        policy_version="2026.1",
        protection_band="95_percent",
        reliability=reliability,
        points=points,
        protected_total=Decimal("1200"),
        expected_total=Decimal("1600"),
        upside_total=Decimal("2000"),
    )


def _guardrails(snapshot: GoalPlanningSnapshot):
    return evaluate_optimization_guardrails(
        snapshot=snapshot,
        ranking=analyze_goal_planning_snapshot(snapshot).ranking,
    )


def test_complete_evidence_is_ready_and_never_exposes_liquid_balance() -> None:
    result = _guardrails(_snapshot())

    assert result.policy_version == OPTIMIZATION_GUARDRAIL_POLICY_VERSION == "2026.1"
    assert result.status is OptimizationGuardrailStatus.READY
    assert result.can_optimize is True
    assert result.liquid_balance_protected == Decimal("2000.0000")
    assert result.emergency_target_amount == Decimal("1500.0000")
    assert result.emergency_fund_gap == Decimal("0.0000")
    assert result.emergency_reserve_amount == Decimal("0.0000")
    assert result.reason_codes == (
        OptimizationGuardrailReasonCode.OPTIMIZATION_READY,
    )


def test_emergency_gap_becomes_a_hard_future_capacity_reserve() -> None:
    result = _guardrails(_snapshot(liquid_balance="200"))

    assert result.status is OptimizationGuardrailStatus.CAUTION
    assert result.can_optimize is True
    assert result.emergency_target_months == Decimal("3.0000")
    assert result.monthly_expense_baseline == Decimal("500.0000")
    assert result.emergency_fund_gap == Decimal("1300.0000")
    assert result.emergency_reserve_amount == Decimal("1300.0000")
    assert OptimizationGuardrailReasonCode.EMERGENCY_RESERVE_REQUIRED in (
        result.reason_codes
    )


def test_incomplete_debt_payment_terms_block_optimization() -> None:
    result = _guardrails(
        _snapshot(
            liabilities=2,
            liability_payments=1,
            warnings=(PlanningSnapshotWarning.DEBT_PAYMENT_INCOMPLETE,),
        )
    )

    assert result.status is OptimizationGuardrailStatus.BLOCKED
    assert result.can_optimize is False
    assert result.outstanding_debt == Decimal("4000.0000")
    assert result.monthly_debt_payment == Decimal("300.0000")
    assert result.debt_payment_evidence_complete is False
    assert (
        OptimizationGuardrailReasonCode.DEBT_PAYMENT_EVIDENCE_INCOMPLETE
        in result.reason_codes
    )


def test_missing_capacity_and_no_goals_fail_closed() -> None:
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        goals=(),
        savings_capacity=None,
        warnings=(
            PlanningSnapshotWarning.NO_ACTIVE_GOALS,
            PlanningSnapshotWarning.SAVINGS_FORECAST_MISSING,
        ),
        provenance=replace(
            snapshot.provenance,
            goal_ids=(),
            forecast_run_id=None,
        ),
    )

    result = _guardrails(snapshot)

    assert result.status is OptimizationGuardrailStatus.BLOCKED
    assert result.protected_capacity_total == Decimal("0.0000")
    assert result.reason_codes[:2] == (
        OptimizationGuardrailReasonCode.PROTECTED_CAPACITY_MISSING,
        OptimizationGuardrailReasonCode.NO_ELIGIBLE_GOALS,
    )


def test_zero_protected_capacity_is_blocked() -> None:
    capacity = _capacity()
    capacity = replace(
        capacity,
        points=tuple(
            replace(point, protected_amount=Decimal("0"))
            for point in capacity.points
        ),
        protected_total=Decimal("0"),
    )

    result = _guardrails(_snapshot(capacity=capacity))

    assert result.status is OptimizationGuardrailStatus.BLOCKED
    assert OptimizationGuardrailReasonCode.PROTECTED_CAPACITY_EMPTY in (
        result.reason_codes
    )


def test_incomplete_soft_evidence_remains_visible_without_inventing_a_target() -> None:
    snapshot = _snapshot(
        capacity=_capacity(reliability="provisional"),
        profile=None,
        budget_count=0,
        budget_limit_count=0,
        budget_limit="0",
        warnings=(PlanningSnapshotWarning.MIXED_CURRENCY_GOALS_EXCLUDED,),
    )

    result = _guardrails(snapshot)

    assert result.status is OptimizationGuardrailStatus.CAUTION
    assert result.emergency_target_months == DEFAULT_EMERGENCY_FUND_TARGET_MONTHS
    assert result.emergency_target_amount is None
    assert result.emergency_fund_gap is None
    assert result.emergency_reserve_amount == Decimal("0.0000")
    assert result.reason_codes == (
        OptimizationGuardrailReasonCode.FORECAST_PROVISIONAL,
        OptimizationGuardrailReasonCode.PROFILE_MISSING,
        OptimizationGuardrailReasonCode.BUDGET_MISSING,
        OptimizationGuardrailReasonCode.EMERGENCY_BASELINE_UNAVAILABLE,
        OptimizationGuardrailReasonCode.MIXED_CURRENCY_GOALS_EXCLUDED,
    )


def test_partial_budget_and_draft_profile_are_cautions() -> None:
    profile = PlanningProfileEvidence(
        completion_status=ProfileCompletionStatus.DRAFT,
        income_stability=None,
        emergency_fund_target_months=None,
        updated_at=_NOW,
    )
    result = _guardrails(
        _snapshot(
            profile=profile,
            budget_count=2,
            budget_limit_count=1,
        )
    )

    assert result.status is OptimizationGuardrailStatus.CAUTION
    assert OptimizationGuardrailReasonCode.PROFILE_INCOMPLETE in result.reason_codes
    assert (
        OptimizationGuardrailReasonCode.BUDGET_LIMIT_INCOMPLETE
        in result.reason_codes
    )


def test_guardrails_reject_ranking_from_another_snapshot() -> None:
    snapshot = _snapshot()
    ranking = replace(
        analyze_goal_planning_snapshot(snapshot).ranking,
        snapshot_id="b" * 64,
    )

    with pytest.raises(ValueError, match="identifiers"):
        evaluate_optimization_guardrails(snapshot=snapshot, ranking=ranking)
