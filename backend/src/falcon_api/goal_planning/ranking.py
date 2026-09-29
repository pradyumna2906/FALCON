"""Explainable deterministic ranking for independently assessed goals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from uuid import UUID

from falcon_api.goal_planning.feasibility import (
    GoalDeadlineRiskLevel,
    GoalFeasibilityAssessment,
    GoalFeasibilityState,
)
from falcon_api.goal_planning.progress import GoalProgress
from falcon_api.models.enums import GoalPriority, GoalType


RANKING_POLICY_VERSION = "2026.1"
SCORE_QUANTUM = Decimal("0.0001")

_PRIORITY_POINTS = {
    GoalPriority.LOW: Decimal("10"),
    GoalPriority.MEDIUM: Decimal("20"),
    GoalPriority.HIGH: Decimal("30"),
    GoalPriority.CRITICAL: Decimal("40"),
}
_GOAL_TYPE_POINTS = {
    GoalType.EMERGENCY_FUND: Decimal("15"),
    GoalType.EDUCATION: Decimal("12"),
    GoalType.MARRIAGE: Decimal("8"),
    GoalType.MAJOR_PURCHASE: Decimal("6"),
    GoalType.OTHER: Decimal("5"),
    GoalType.TRAVEL: Decimal("4"),
}
_RISK_POINTS = {
    GoalDeadlineRiskLevel.FUNDED: Decimal("0"),
    GoalDeadlineRiskLevel.LOW: Decimal("2"),
    GoalDeadlineRiskLevel.MODERATE: Decimal("5"),
    GoalDeadlineRiskLevel.HIGH: Decimal("8"),
    GoalDeadlineRiskLevel.CRITICAL: Decimal("10"),
    GoalDeadlineRiskLevel.OVERDUE: Decimal("10"),
    GoalDeadlineRiskLevel.UNKNOWN: Decimal("5"),
}


class GoalRankingReasonCode(StrEnum):
    """Stable reasons behind a ranking score."""

    USER_PRIORITY_LOW = "user_priority_low"
    USER_PRIORITY_MEDIUM = "user_priority_medium"
    USER_PRIORITY_HIGH = "user_priority_high"
    USER_PRIORITY_CRITICAL = "user_priority_critical"
    DEADLINE_OVERDUE = "deadline_overdue"
    DEADLINE_IMMEDIATE = "deadline_immediate"
    DEADLINE_NEAR_TERM = "deadline_near_term"
    DEADLINE_MEDIUM_TERM = "deadline_medium_term"
    DEADLINE_LONG_TERM = "deadline_long_term"
    EMERGENCY_FUND_SAFETY = "emergency_fund_safety"
    EDUCATION_GOAL = "education_goal"
    USER_DEFINED_GOAL_TYPE = "user_defined_goal_type"
    DEADLINE_RISK_LOW = "deadline_risk_low"
    DEADLINE_RISK_ELEVATED = "deadline_risk_elevated"
    DEADLINE_RISK_UNKNOWN = "deadline_risk_unknown"
    NO_PROGRESS = "no_progress"
    PARTIAL_PROGRESS = "partial_progress"
    NEAR_COMPLETION = "near_completion"
    ALREADY_FUNDED = "already_funded"


@dataclass(frozen=True, slots=True)
class GoalRankingScore:
    """Auditable components of the bounded 0–100 ranking score."""

    user_priority: Decimal
    deadline_urgency: Decimal
    goal_type_safety: Decimal
    deadline_risk: Decimal
    completion_momentum: Decimal
    total: Decimal


@dataclass(frozen=True, slots=True)
class RankedGoal:
    """One stable ranking result consumed by allocation policies."""

    rank: int
    goal_id: UUID
    goal_name: str
    goal_type: GoalType
    user_priority: GoalPriority
    target_date: date
    eligible_for_allocation: bool
    score: GoalRankingScore
    feasibility_state: GoalFeasibilityState
    deadline_risk: GoalDeadlineRiskLevel
    completion_probability: Decimal | None
    reason_codes: tuple[GoalRankingReasonCode, ...]


@dataclass(frozen=True, slots=True)
class GoalRanking:
    """Versioned deterministic order for one immutable planning snapshot."""

    snapshot_id: str
    policy_version: str
    items: tuple[RankedGoal, ...]


def rank_goal_assessments(
    *,
    snapshot_id: str,
    goals: tuple[GoalProgress, ...],
    assessments: tuple[GoalFeasibilityAssessment, ...],
) -> GoalRanking:
    """Rank goals without assigning or moving any money."""
    assessment_by_id = _assessment_index(goals=goals, assessments=assessments)
    scored = [
        _scored_goal(goal=goal, assessment=assessment_by_id[goal.goal_id])
        for goal in goals
    ]
    scored.sort(
        key=lambda item: (
            not item.eligible_for_allocation,
            -item.score.total,
            -item.score.user_priority,
            item.target_date,
            -item.score.completion_momentum,
            str(item.goal_id),
        )
    )
    return GoalRanking(
        snapshot_id=snapshot_id,
        policy_version=RANKING_POLICY_VERSION,
        items=tuple(
            RankedGoal(
                rank=index,
                goal_id=item.goal_id,
                goal_name=item.goal_name,
                goal_type=item.goal_type,
                user_priority=item.user_priority,
                target_date=item.target_date,
                eligible_for_allocation=item.eligible_for_allocation,
                score=item.score,
                feasibility_state=item.feasibility_state,
                deadline_risk=item.deadline_risk,
                completion_probability=item.completion_probability,
                reason_codes=item.reason_codes,
            )
            for index, item in enumerate(scored, start=1)
        ),
    )


def _assessment_index(
    *,
    goals: tuple[GoalProgress, ...],
    assessments: tuple[GoalFeasibilityAssessment, ...],
) -> dict[UUID, GoalFeasibilityAssessment]:
    goal_ids = [goal.goal_id for goal in goals]
    if len(set(goal_ids)) != len(goal_ids):
        raise ValueError("Goals must be unique before ranking.")
    result: dict[UUID, GoalFeasibilityAssessment] = {}
    for assessment in assessments:
        if assessment.goal_id in result:
            raise ValueError("Goal feasibility assessments must be unique.")
        result[assessment.goal_id] = assessment
    if set(result) != set(goal_ids):
        raise ValueError(
            "Every ranked goal requires exactly one feasibility assessment."
        )
    return result


def _scored_goal(
    *,
    goal: GoalProgress,
    assessment: GoalFeasibilityAssessment,
) -> RankedGoal:
    priority = GoalPriority(goal.priority)
    goal_type = GoalType(goal.goal_type)
    priority_points = _PRIORITY_POINTS[priority]
    urgency_points, urgency_reason = _urgency(goal.months_remaining)
    type_points = _GOAL_TYPE_POINTS[goal_type]
    risk_points = _RISK_POINTS[assessment.deadline_risk]
    momentum_points, momentum_reason = _momentum(goal)
    total = (
        priority_points
        + urgency_points
        + type_points
        + risk_points
        + momentum_points
    ).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)
    reasons = (
        _priority_reason(priority),
        urgency_reason,
        _goal_type_reason(goal_type),
        _risk_reason(assessment.deadline_risk),
        momentum_reason,
    )
    return RankedGoal(
        rank=0,
        goal_id=goal.goal_id,
        goal_name=goal.goal_name,
        goal_type=goal_type,
        user_priority=priority,
        target_date=goal.target_date,
        eligible_for_allocation=(
            goal.remaining_amount > 0 and goal.target_date > goal.calculated_on
        ),
        score=GoalRankingScore(
            user_priority=priority_points.quantize(SCORE_QUANTUM),
            deadline_urgency=urgency_points.quantize(SCORE_QUANTUM),
            goal_type_safety=type_points.quantize(SCORE_QUANTUM),
            deadline_risk=risk_points.quantize(SCORE_QUANTUM),
            completion_momentum=momentum_points.quantize(SCORE_QUANTUM),
            total=total,
        ),
        feasibility_state=assessment.feasibility_state,
        deadline_risk=assessment.deadline_risk,
        completion_probability=assessment.completion_probability,
        reason_codes=reasons,
    )


def _urgency(months_remaining: int) -> tuple[Decimal, GoalRankingReasonCode]:
    if months_remaining <= 0:
        return Decimal("25"), GoalRankingReasonCode.DEADLINE_OVERDUE
    if months_remaining <= 1:
        return Decimal("25"), GoalRankingReasonCode.DEADLINE_IMMEDIATE
    if months_remaining <= 3:
        return Decimal("22"), GoalRankingReasonCode.DEADLINE_NEAR_TERM
    if months_remaining <= 6:
        return Decimal("18"), GoalRankingReasonCode.DEADLINE_NEAR_TERM
    if months_remaining <= 12:
        return Decimal("12"), GoalRankingReasonCode.DEADLINE_MEDIUM_TERM
    if months_remaining <= 24:
        return Decimal("6"), GoalRankingReasonCode.DEADLINE_LONG_TERM
    return Decimal("2"), GoalRankingReasonCode.DEADLINE_LONG_TERM


def _momentum(goal: GoalProgress) -> tuple[Decimal, GoalRankingReasonCode]:
    if goal.remaining_amount == 0:
        return Decimal("0"), GoalRankingReasonCode.ALREADY_FUNDED
    points = (goal.funding_ratio * Decimal("10")).quantize(
        SCORE_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
    if goal.funding_ratio >= Decimal("0.75"):
        reason = GoalRankingReasonCode.NEAR_COMPLETION
    elif goal.funding_ratio > 0:
        reason = GoalRankingReasonCode.PARTIAL_PROGRESS
    else:
        reason = GoalRankingReasonCode.NO_PROGRESS
    return points, reason


def _priority_reason(priority: GoalPriority) -> GoalRankingReasonCode:
    return {
        GoalPriority.LOW: GoalRankingReasonCode.USER_PRIORITY_LOW,
        GoalPriority.MEDIUM: GoalRankingReasonCode.USER_PRIORITY_MEDIUM,
        GoalPriority.HIGH: GoalRankingReasonCode.USER_PRIORITY_HIGH,
        GoalPriority.CRITICAL: GoalRankingReasonCode.USER_PRIORITY_CRITICAL,
    }[priority]


def _goal_type_reason(goal_type: GoalType) -> GoalRankingReasonCode:
    if goal_type is GoalType.EMERGENCY_FUND:
        return GoalRankingReasonCode.EMERGENCY_FUND_SAFETY
    if goal_type is GoalType.EDUCATION:
        return GoalRankingReasonCode.EDUCATION_GOAL
    return GoalRankingReasonCode.USER_DEFINED_GOAL_TYPE


def _risk_reason(risk: GoalDeadlineRiskLevel) -> GoalRankingReasonCode:
    if risk in {GoalDeadlineRiskLevel.FUNDED, GoalDeadlineRiskLevel.LOW}:
        return GoalRankingReasonCode.DEADLINE_RISK_LOW
    if risk is GoalDeadlineRiskLevel.UNKNOWN:
        return GoalRankingReasonCode.DEADLINE_RISK_UNKNOWN
    return GoalRankingReasonCode.DEADLINE_RISK_ELEVATED
