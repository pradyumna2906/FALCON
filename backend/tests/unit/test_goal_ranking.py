"""Checkpoint 10.7 explainable goal-ranking policy tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from falcon_api.goal_planning import (
    RANKING_POLICY_VERSION,
    GoalRankingReasonCode,
    SavingsCapacityPlan,
    SavingsCapacityPoint,
    assess_snapshot_feasibility,
    calculate_goal_progress,
    rank_goal_assessments,
)
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def _progress(
    *,
    goal_id: UUID | None = None,
    name: str = "Goal",
    priority: GoalPriority = GoalPriority.MEDIUM,
    goal_type: GoalType = GoalType.OTHER,
    deadline: date = date(2026, 12, 31),
    target: str = "1000",
    starting: str = "100",
):
    goal = Goal(
        id=goal_id or uuid4(),
        user_id=uuid4(),
        name=name,
        goal_type=goal_type,
        target_amount=Decimal(target),
        starting_amount=Decimal(starting),
        currency="INR",
        target_date=deadline,
        priority=priority,
        status=GoalStatus.ACTIVE,
        description=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return calculate_goal_progress(
        goal=goal,
        contribution_amount=Decimal("0"),
        calculated_on=date(2026, 9, 15),
    )


def _capacity() -> SavingsCapacityPlan:
    points = tuple(
        SavingsCapacityPoint(
            period_start=period,
            protected_amount=Decimal("200"),
            expected_amount=Decimal("400"),
            upside_amount=Decimal("600"),
        )
        for period in (
            date(2026, 10, 1),
            date(2026, 11, 1),
            date(2026, 12, 1),
        )
    )
    return SavingsCapacityPlan(
        forecast_run_id=uuid4(),
        currency="INR",
        policy_version="2026.1",
        protection_band="95_percent",
        reliability="normal",
        points=points,
        protected_total=Decimal("600"),
        expected_total=Decimal("1200"),
        upside_total=Decimal("1800"),
    )


def _rank(goals, *, capacity=None):
    resolved_capacity = _capacity() if capacity is None else capacity
    assessments = assess_snapshot_feasibility(goals, resolved_capacity)
    return rank_goal_assessments(
        snapshot_id="a" * 64,
        goals=goals,
        assessments=assessments,
    )


def test_ranking_combines_bounded_components_and_user_priority_dominates() -> None:
    critical = _progress(
        name="Emergency reserve",
        priority=GoalPriority.CRITICAL,
        goal_type=GoalType.EMERGENCY_FUND,
    )
    low = _progress(
        name="Travel",
        priority=GoalPriority.LOW,
        goal_type=GoalType.TRAVEL,
    )

    result = _rank((low, critical))

    assert result.policy_version == RANKING_POLICY_VERSION == "2026.1"
    assert tuple(item.goal_id for item in result.items) == (
        critical.goal_id,
        low.goal_id,
    )
    assert tuple(item.rank for item in result.items) == (1, 2)
    first = result.items[0]
    assert first.score.total == sum(
        (
            first.score.user_priority,
            first.score.deadline_urgency,
            first.score.goal_type_safety,
            first.score.deadline_risk,
            first.score.completion_momentum,
        ),
        Decimal("0"),
    )
    assert Decimal("0") <= first.score.total <= Decimal("100")
    assert GoalRankingReasonCode.USER_PRIORITY_CRITICAL in first.reason_codes
    assert GoalRankingReasonCode.EMERGENCY_FUND_SAFETY in first.reason_codes


def test_ranking_uses_stable_uuid_tie_breaker() -> None:
    first = _progress(goal_id=UUID(int=1))
    second = _progress(goal_id=UUID(int=2))

    original = _rank((second, first))
    repeated = _rank((first, second))

    assert tuple(item.goal_id for item in original.items) == (
        first.goal_id,
        second.goal_id,
    )
    assert tuple(item.goal_id for item in repeated.items) == (
        first.goal_id,
        second.goal_id,
    )


@pytest.mark.parametrize(
    ("priority", "reason", "points"),
    [
        (GoalPriority.LOW, GoalRankingReasonCode.USER_PRIORITY_LOW, "10"),
        (GoalPriority.MEDIUM, GoalRankingReasonCode.USER_PRIORITY_MEDIUM, "20"),
        (GoalPriority.HIGH, GoalRankingReasonCode.USER_PRIORITY_HIGH, "30"),
        (GoalPriority.CRITICAL, GoalRankingReasonCode.USER_PRIORITY_CRITICAL, "40"),
    ],
)
def test_user_priority_component_is_explicit(
    priority: GoalPriority,
    reason: GoalRankingReasonCode,
    points: str,
) -> None:
    item = _rank((_progress(priority=priority),)).items[0]

    assert item.score.user_priority == Decimal(points).quantize(Decimal("0.0001"))
    assert reason in item.reason_codes


@pytest.mark.parametrize(
    ("deadline", "expected_points", "expected_reason"),
    [
        (date(2026, 9, 15), "25", GoalRankingReasonCode.DEADLINE_OVERDUE),
        (date(2026, 10, 1), "25", GoalRankingReasonCode.DEADLINE_IMMEDIATE),
        (date(2026, 12, 1), "22", GoalRankingReasonCode.DEADLINE_NEAR_TERM),
        (date(2027, 3, 15), "18", GoalRankingReasonCode.DEADLINE_NEAR_TERM),
        (date(2027, 9, 15), "12", GoalRankingReasonCode.DEADLINE_MEDIUM_TERM),
        (date(2028, 9, 15), "6", GoalRankingReasonCode.DEADLINE_LONG_TERM),
        (date(2030, 9, 15), "2", GoalRankingReasonCode.DEADLINE_LONG_TERM),
    ],
)
def test_deadline_urgency_bands_are_versioned_and_explainable(
    deadline: date,
    expected_points: str,
    expected_reason: GoalRankingReasonCode,
) -> None:
    item = _rank((_progress(deadline=deadline),)).items[0]

    assert item.score.deadline_urgency == Decimal(expected_points).quantize(
        Decimal("0.0001")
    )
    assert expected_reason in item.reason_codes


def test_goal_type_and_risk_reasons_cover_safety_education_and_unknown() -> None:
    education = _rank((_progress(goal_type=GoalType.EDUCATION),)).items[0]
    unknown_goal = _progress(goal_type=GoalType.MAJOR_PURCHASE)
    unknown_assessment = assess_snapshot_feasibility((unknown_goal,), None)
    unknown = rank_goal_assessments(
        snapshot_id="b" * 64,
        goals=(unknown_goal,),
        assessments=unknown_assessment,
    ).items[0]

    assert GoalRankingReasonCode.EDUCATION_GOAL in education.reason_codes
    assert GoalRankingReasonCode.USER_DEFINED_GOAL_TYPE in unknown.reason_codes
    assert GoalRankingReasonCode.DEADLINE_RISK_UNKNOWN in unknown.reason_codes


@pytest.mark.parametrize(
    ("starting", "reason", "eligible"),
    [
        ("0", GoalRankingReasonCode.NO_PROGRESS, True),
        ("500", GoalRankingReasonCode.PARTIAL_PROGRESS, True),
        ("800", GoalRankingReasonCode.NEAR_COMPLETION, True),
        ("1000", GoalRankingReasonCode.ALREADY_FUNDED, False),
    ],
)
def test_completion_momentum_and_eligibility_are_explicit(
    starting: str,
    reason: GoalRankingReasonCode,
    eligible: bool,
) -> None:
    item = _rank((_progress(starting=starting),)).items[0]

    assert reason in item.reason_codes
    assert item.eligible_for_allocation is eligible


def test_ineligible_funded_goal_is_sorted_after_allocatable_goal() -> None:
    funded = _progress(
        priority=GoalPriority.CRITICAL,
        goal_type=GoalType.EMERGENCY_FUND,
        starting="1000",
    )
    allocatable = _progress(priority=GoalPriority.LOW, starting="0")

    result = _rank((funded, allocatable))

    assert result.items[0].goal_id == allocatable.goal_id
    assert result.items[1].goal_id == funded.goal_id


def test_ranking_rejects_missing_or_duplicate_assessments() -> None:
    first = _progress()
    second = _progress()
    first_assessment = assess_snapshot_feasibility((first,), _capacity())[0]

    with pytest.raises(ValueError, match="exactly one"):
        rank_goal_assessments(
            snapshot_id="a" * 64,
            goals=(first, second),
            assessments=(first_assessment,),
        )
    with pytest.raises(ValueError, match="unique"):
        rank_goal_assessments(
            snapshot_id="a" * 64,
            goals=(first,),
            assessments=(first_assessment, first_assessment),
        )
    with pytest.raises(ValueError, match="Goals must be unique"):
        rank_goal_assessments(
            snapshot_id="a" * 64,
            goals=(first, first),
            assessments=(first_assessment,),
        )
