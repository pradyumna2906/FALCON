"""Per-goal feasibility, probability, and deadline-risk evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from uuid import UUID

from falcon_api.analytics.types import money
from falcon_api.goal_planning.capacity import (
    SavingsCapacityPlan,
    SavingsCapacityPoint,
)
from falcon_api.goal_planning.progress import GoalProgress


FEASIBILITY_POLICY_VERSION = "2026.1"
PROBABILITY_QUANTUM = Decimal("0.000001")


class GoalFeasibilityState(StrEnum):
    """Independent achievability state before multi-goal allocation."""

    FUNDED = "funded"
    SECURE = "secure"
    FEASIBLE = "feasible"
    STRETCH = "stretch"
    UNLIKELY = "unlikely"
    INDETERMINATE = "indeterminate"
    OVERDUE = "overdue"
    UNAVAILABLE = "unavailable"


class GoalDeadlineRiskLevel(StrEnum):
    """Deadline exposure inferred from protected, expected, and upside capacity."""

    FUNDED = "funded"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
    OVERDUE = "overdue"
    UNKNOWN = "unknown"


class FeasibilityEvidenceReliability(StrEnum):
    """Quality of the evidence supporting one goal assessment."""

    NORMAL = "normal"
    PROVISIONAL = "provisional"
    LIMITED_HORIZON = "limited_horizon"
    UNAVAILABLE = "unavailable"


class GoalFeasibilityReasonCode(StrEnum):
    """Stable, non-generative explanations for feasibility results."""

    ALREADY_FUNDED = "already_funded"
    DEADLINE_PASSED = "deadline_passed"
    CAPACITY_EVIDENCE_MISSING = "capacity_evidence_missing"
    FORECAST_STARTS_AFTER_DEADLINE = "forecast_starts_after_deadline"
    FORECAST_HORIZON_BEFORE_DEADLINE = "forecast_horizon_before_deadline"
    FORECAST_PROVISIONAL = "forecast_provisional"
    PROTECTED_CAPACITY_SUFFICIENT = "protected_capacity_sufficient"
    EXPECTED_CAPACITY_SUFFICIENT = "expected_capacity_sufficient"
    UPSIDE_CAPACITY_REQUIRED = "upside_capacity_required"
    UPSIDE_CAPACITY_INSUFFICIENT = "upside_capacity_insufficient"


@dataclass(frozen=True, slots=True)
class GoalCompletionWindow:
    """First forecast month in which each capacity band funds the goal."""

    protected_period: date | None
    expected_period: date | None
    upside_period: date | None


@dataclass(frozen=True, slots=True)
class GoalFeasibilityAssessment:
    """Explainable independent assessment for one active goal."""

    goal_id: UUID
    policy_version: str
    feasibility_state: GoalFeasibilityState
    deadline_risk: GoalDeadlineRiskLevel
    completion_probability: Decimal | None
    probability_method: str
    remaining_amount: Decimal
    protected_capacity_by_deadline: Decimal
    expected_capacity_by_deadline: Decimal
    upside_capacity_by_deadline: Decimal
    protected_shortfall: Decimal
    expected_shortfall: Decimal
    upside_shortfall: Decimal
    completion_window: GoalCompletionWindow
    forecast_horizon_end: date | None
    evidence_reliability: FeasibilityEvidenceReliability
    reason_codes: tuple[GoalFeasibilityReasonCode, ...]


def assess_goal_feasibility(
    progress: GoalProgress,
    capacity: SavingsCapacityPlan | None,
) -> GoalFeasibilityAssessment:
    """Assess one goal against shared capacity without allocating that capacity."""
    remaining = money(progress.remaining_amount)
    points = _validated_points(progress=progress, capacity=capacity)
    horizon_end = points[-1].period_start if points else None
    by_deadline = tuple(
        point for point in points if point.period_start <= progress.target_date
    )
    protected = _capacity_total(by_deadline, "protected_amount")
    expected = _capacity_total(by_deadline, "expected_amount")
    upside = _capacity_total(by_deadline, "upside_amount")
    completion = GoalCompletionWindow(
        protected_period=_completion_period(
            points, remaining=remaining, field="protected_amount"
        ),
        expected_period=_completion_period(
            points, remaining=remaining, field="expected_amount"
        ),
        upside_period=_completion_period(
            points, remaining=remaining, field="upside_amount"
        ),
    )
    if remaining == 0:
        completion = GoalCompletionWindow(
            protected_period=progress.calculated_on,
            expected_period=progress.calculated_on,
            upside_period=progress.calculated_on,
        )
        return _assessment(
            progress=progress,
            state=GoalFeasibilityState.FUNDED,
            risk=GoalDeadlineRiskLevel.FUNDED,
            probability=Decimal("1"),
            remaining=remaining,
            protected=protected,
            expected=expected,
            upside=upside,
            completion=completion,
            horizon_end=horizon_end,
            reliability=_reliability(
                progress=progress,
                capacity=capacity,
                points=points,
            ),
            reasons=(GoalFeasibilityReasonCode.ALREADY_FUNDED,),
        )
    if progress.target_date <= progress.calculated_on:
        return _assessment(
            progress=progress,
            state=GoalFeasibilityState.OVERDUE,
            risk=GoalDeadlineRiskLevel.OVERDUE,
            probability=Decimal("0"),
            remaining=remaining,
            protected=protected,
            expected=expected,
            upside=upside,
            completion=completion,
            horizon_end=horizon_end,
            reliability=_reliability(
                progress=progress,
                capacity=capacity,
                points=points,
            ),
            reasons=(GoalFeasibilityReasonCode.DEADLINE_PASSED,),
        )
    if capacity is None or not points:
        return _assessment(
            progress=progress,
            state=GoalFeasibilityState.UNAVAILABLE,
            risk=GoalDeadlineRiskLevel.UNKNOWN,
            probability=None,
            remaining=remaining,
            protected=protected,
            expected=expected,
            upside=upside,
            completion=completion,
            horizon_end=horizon_end,
            reliability=FeasibilityEvidenceReliability.UNAVAILABLE,
            reasons=(GoalFeasibilityReasonCode.CAPACITY_EVIDENCE_MISSING,),
        )

    covers_deadline = horizon_end is not None and horizon_end >= date(
        progress.target_date.year,
        progress.target_date.month,
        1,
    )
    state, risk, primary_reason = _classify(
        remaining=remaining,
        protected=protected,
        expected=expected,
        upside=upside,
        covers_deadline=covers_deadline,
    )
    reasons: list[GoalFeasibilityReasonCode] = []
    if by_deadline == () and points[0].period_start > progress.target_date:
        reasons.append(GoalFeasibilityReasonCode.FORECAST_STARTS_AFTER_DEADLINE)
    if not covers_deadline:
        reasons.append(GoalFeasibilityReasonCode.FORECAST_HORIZON_BEFORE_DEADLINE)
    if capacity.reliability == "provisional":
        reasons.append(GoalFeasibilityReasonCode.FORECAST_PROVISIONAL)
    reasons.append(primary_reason)
    probability = (
        _completion_probability(
            remaining=remaining,
            protected=protected,
            expected=expected,
            upside=upside,
        )
        if covers_deadline or upside >= remaining
        else None
    )
    return _assessment(
        progress=progress,
        state=state,
        risk=risk,
        probability=probability,
        remaining=remaining,
        protected=protected,
        expected=expected,
        upside=upside,
        completion=completion,
        horizon_end=horizon_end,
        reliability=_reliability(progress=progress, capacity=capacity, points=points),
        reasons=tuple(reasons),
    )


def assess_snapshot_feasibility(
    goals: tuple[GoalProgress, ...],
    capacity: SavingsCapacityPlan | None,
) -> tuple[GoalFeasibilityAssessment, ...]:
    """Assess snapshot goals in their immutable order."""
    return tuple(assess_goal_feasibility(goal, capacity) for goal in goals)


def _validated_points(
    *,
    progress: GoalProgress,
    capacity: SavingsCapacityPlan | None,
) -> tuple[SavingsCapacityPoint, ...]:
    if capacity is None:
        return ()
    if capacity.currency != progress.currency:
        raise ValueError("Goal and savings capacity currencies must match.")
    points = tuple(sorted(capacity.points, key=lambda point: point.period_start))
    if len({point.period_start for point in points}) != len(points):
        raise ValueError("Savings capacity periods must be unique.")
    for point in points:
        if not (
            Decimal("0")
            <= point.protected_amount
            <= point.expected_amount
            <= point.upside_amount
        ):
            raise ValueError("Savings capacity bands must be ordered and non-negative.")
    return points


def _capacity_total(
    points: tuple[SavingsCapacityPoint, ...],
    field: str,
) -> Decimal:
    return money(sum((getattr(point, field) for point in points), Decimal("0")))


def _completion_period(
    points: tuple[SavingsCapacityPoint, ...],
    *,
    remaining: Decimal,
    field: str,
) -> date | None:
    if remaining == 0:
        return None
    cumulative = Decimal("0")
    for point in points:
        cumulative += getattr(point, field)
        if cumulative >= remaining:
            return point.period_start
    return None


def _classify(
    *,
    remaining: Decimal,
    protected: Decimal,
    expected: Decimal,
    upside: Decimal,
    covers_deadline: bool,
) -> tuple[
    GoalFeasibilityState,
    GoalDeadlineRiskLevel,
    GoalFeasibilityReasonCode,
]:
    if protected >= remaining:
        return (
            GoalFeasibilityState.SECURE,
            GoalDeadlineRiskLevel.LOW,
            GoalFeasibilityReasonCode.PROTECTED_CAPACITY_SUFFICIENT,
        )
    if expected >= remaining:
        return (
            GoalFeasibilityState.FEASIBLE,
            GoalDeadlineRiskLevel.MODERATE,
            GoalFeasibilityReasonCode.EXPECTED_CAPACITY_SUFFICIENT,
        )
    if upside >= remaining:
        return (
            GoalFeasibilityState.STRETCH,
            GoalDeadlineRiskLevel.HIGH,
            GoalFeasibilityReasonCode.UPSIDE_CAPACITY_REQUIRED,
        )
    if not covers_deadline:
        return (
            GoalFeasibilityState.INDETERMINATE,
            GoalDeadlineRiskLevel.UNKNOWN,
            GoalFeasibilityReasonCode.UPSIDE_CAPACITY_INSUFFICIENT,
        )
    return (
        GoalFeasibilityState.UNLIKELY,
        GoalDeadlineRiskLevel.CRITICAL,
        GoalFeasibilityReasonCode.UPSIDE_CAPACITY_INSUFFICIENT,
    )


def _completion_probability(
    *,
    remaining: Decimal,
    protected: Decimal,
    expected: Decimal,
    upside: Decimal,
) -> Decimal:
    """Interpolate the forecast's 95% band without stochastic simulation."""
    if remaining <= protected:
        result = Decimal("0.975")
    elif remaining <= expected and expected > protected:
        position = (remaining - protected) / (expected - protected)
        result = Decimal("0.975") - Decimal("0.475") * position
    elif remaining <= upside and upside > expected:
        position = (remaining - expected) / (upside - expected)
        result = Decimal("0.5") - Decimal("0.475") * position
    else:
        result = Decimal("0")
    return min(Decimal("1"), max(Decimal("0"), result)).quantize(
        PROBABILITY_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _reliability(
    *,
    progress: GoalProgress,
    capacity: SavingsCapacityPlan | None,
    points: tuple[SavingsCapacityPoint, ...],
) -> FeasibilityEvidenceReliability:
    if capacity is None or not points:
        return FeasibilityEvidenceReliability.UNAVAILABLE
    deadline_month = date(progress.target_date.year, progress.target_date.month, 1)
    if points[-1].period_start < deadline_month:
        return FeasibilityEvidenceReliability.LIMITED_HORIZON
    if capacity.reliability == "provisional":
        return FeasibilityEvidenceReliability.PROVISIONAL
    return FeasibilityEvidenceReliability.NORMAL


def _assessment(
    *,
    progress: GoalProgress,
    state: GoalFeasibilityState,
    risk: GoalDeadlineRiskLevel,
    probability: Decimal | None,
    remaining: Decimal,
    protected: Decimal,
    expected: Decimal,
    upside: Decimal,
    completion: GoalCompletionWindow,
    horizon_end: date | None,
    reliability: FeasibilityEvidenceReliability,
    reasons: tuple[GoalFeasibilityReasonCode, ...],
) -> GoalFeasibilityAssessment:
    return GoalFeasibilityAssessment(
        goal_id=progress.goal_id,
        policy_version=FEASIBILITY_POLICY_VERSION,
        feasibility_state=state,
        deadline_risk=risk,
        completion_probability=(
            probability.quantize(PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN)
            if probability is not None
            else None
        ),
        probability_method="piecewise_95_percent_capacity_band",
        remaining_amount=remaining,
        protected_capacity_by_deadline=protected,
        expected_capacity_by_deadline=expected,
        upside_capacity_by_deadline=upside,
        protected_shortfall=money(max(Decimal("0"), remaining - protected)),
        expected_shortfall=money(max(Decimal("0"), remaining - expected)),
        upside_shortfall=money(max(Decimal("0"), remaining - upside)),
        completion_window=completion,
        forecast_horizon_end=horizon_end,
        evidence_reliability=reliability,
        reason_codes=reasons,
    )
