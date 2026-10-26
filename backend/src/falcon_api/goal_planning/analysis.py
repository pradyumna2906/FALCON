"""Pure orchestration for Phase 10 feasibility, ranking, and baseline planning."""

from __future__ import annotations

from dataclasses import dataclass

from falcon_api.goal_planning.feasibility import (
    FEASIBILITY_POLICY_VERSION,
    GoalFeasibilityAssessment,
    assess_snapshot_feasibility,
)
from falcon_api.goal_planning.greedy import (
    GreedyAllocationBaseline,
    build_greedy_allocation_baseline,
)
from falcon_api.goal_planning.ranking import GoalRanking, rank_goal_assessments
from falcon_api.goal_planning.snapshot import GoalPlanningSnapshot


@dataclass(frozen=True, slots=True)
class GoalPlanningAnalysis:
    """Non-persistent Batch 3 output tied to one immutable snapshot."""

    snapshot_id: str
    feasibility_policy_version: str
    assessments: tuple[GoalFeasibilityAssessment, ...]
    ranking: GoalRanking
    greedy_baseline: GreedyAllocationBaseline


def analyze_goal_planning_snapshot(
    snapshot: GoalPlanningSnapshot,
) -> GoalPlanningAnalysis:
    """Run the complete deterministic Checkpoint 10.6–10.8 chain."""
    assessments = assess_snapshot_feasibility(
        snapshot.goals,
        snapshot.savings_capacity,
    )
    ranking = rank_goal_assessments(
        snapshot_id=snapshot.snapshot_id,
        goals=snapshot.goals,
        assessments=assessments,
    )
    baseline = build_greedy_allocation_baseline(
        snapshot=snapshot,
        ranking=ranking,
    )
    return GoalPlanningAnalysis(
        snapshot_id=snapshot.snapshot_id,
        feasibility_policy_version=FEASIBILITY_POLICY_VERSION,
        assessments=assessments,
        ranking=ranking,
        greedy_baseline=baseline,
    )
