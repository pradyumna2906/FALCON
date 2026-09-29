"""Bounded privacy-safe monitoring for goal-plan generation and decisions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from time import perf_counter

from falcon_api.goal_planning.feasibility import FeasibilityEvidenceReliability
from falcon_api.goal_planning.optimizer import ConstrainedOptimizationStatus
from falcon_api.goal_planning.plan import GoalPlanStrategy
from falcon_api.models.enums import GoalPlanStatus
from falcon_api.models.goal_plan import GoalPlanRun


GOAL_PLAN_OPERATION_POLICY_VERSION = "2026.1"


class GoalPlanOperation(StrEnum):
    """Closed low-cardinality goal-plan operations."""

    GENERATE = "generate"
    REGENERATE = "regenerate"
    APPROVE = "approve"
    REJECT = "reject"


class GoalPlanMonitor:
    """Emit aggregate operational fields without identities or financial values."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._logger = logger or logging.getLogger("falcon_api.goal_planning")
        self._timer = timer

    def start(self) -> float:
        return self._timer()

    def record_generation(
        self,
        run: GoalPlanRun,
        *,
        operation: GoalPlanOperation,
        started_at: float,
    ) -> None:
        resolved_operation = GoalPlanOperation(operation)
        if resolved_operation not in {
            GoalPlanOperation.GENERATE,
            GoalPlanOperation.REGENERATE,
        }:
            raise ValueError("Goal-plan generation telemetry operation is invalid.")
        if run.goal_count < 0 or run.feasible_goal_count < 0:
            raise ValueError("Goal-plan telemetry counts cannot be negative.")
        if run.at_risk_goal_count < 0 or run.uncertain_goal_count < 0:
            raise ValueError("Goal-plan telemetry counts cannot be negative.")
        if (
            run.feasible_goal_count
            + run.at_risk_goal_count
            + run.uncertain_goal_count
            != run.goal_count
        ):
            raise ValueError("Goal-plan telemetry counts must reconcile.")
        capacity = Decimal(run.available_savings)
        allocated = Decimal(run.allocated_savings)
        if (
            not capacity.is_finite()
            or not allocated.is_finite()
            or capacity < 0
            or allocated < 0
            or allocated > capacity
        ):
            raise ValueError("Goal-plan telemetry totals are invalid.")
        strategy = GoalPlanStrategy(run.strategy)
        solver_result = (
            ConstrainedOptimizationStatus(run.optimizer_status).value
            if run.optimizer_status is not None
            else "not_run"
        )
        reliability = FeasibilityEvidenceReliability(
            run.forecast_reliability
        )
        horizon = len(run.periods)
        self._logger.info(
            "goal_plan_generation_completed",
            extra={
                "goal_plan_operation_policy_version": (
                    GOAL_PLAN_OPERATION_POLICY_VERSION
                ),
                "goal_plan_operation": resolved_operation.value,
                "goal_plan_goal_count_band": _count_band(run.goal_count),
                "goal_plan_horizon_band": _count_band(horizon),
                "goal_plan_strategy": strategy.value,
                "goal_plan_solver_result": solver_result,
                "goal_plan_feasible_count_band": _count_band(
                    run.feasible_goal_count
                ),
                "goal_plan_at_risk_count_band": _count_band(
                    run.at_risk_goal_count
                ),
                "goal_plan_utilization_band": _utilization_band(
                    allocated=allocated,
                    capacity=capacity,
                ),
                "goal_plan_reliability": reliability.value,
                "duration_ms": _duration_ms(self._timer(), started_at),
            },
        )

    def record_transition(
        self,
        *,
        operation: GoalPlanOperation,
        status: GoalPlanStatus,
        started_at: float,
    ) -> None:
        resolved_operation = GoalPlanOperation(operation)
        expected = {
            GoalPlanOperation.APPROVE: GoalPlanStatus.APPROVED,
            GoalPlanOperation.REJECT: GoalPlanStatus.REJECTED,
        }
        if expected.get(resolved_operation) is not GoalPlanStatus(status):
            raise ValueError("Goal-plan transition telemetry is inconsistent.")
        self._logger.info(
            "goal_plan_transition_completed",
            extra={
                "goal_plan_operation_policy_version": (
                    GOAL_PLAN_OPERATION_POLICY_VERSION
                ),
                "goal_plan_operation": resolved_operation.value,
                "goal_plan_status": GoalPlanStatus(status).value,
                "duration_ms": _duration_ms(self._timer(), started_at),
            },
        )


def _count_band(value: int) -> str:
    if type(value) is not int or value < 0:
        raise ValueError("Goal-plan telemetry counts must be non-negative integers.")
    if value == 0:
        return "000"
    if value <= 3:
        return "001_003"
    if value <= 10:
        return "004_010"
    if value <= 25:
        return "011_025"
    if value <= 50:
        return "026_050"
    return "051_plus"


def _utilization_band(*, allocated: Decimal, capacity: Decimal) -> str:
    if capacity == 0:
        return "none"
    percentage = allocated / capacity
    if percentage < Decimal("0.25"):
        return "under_25_percent"
    if percentage < Decimal("0.50"):
        return "25_49_percent"
    if percentage < Decimal("0.75"):
        return "50_74_percent"
    if percentage < Decimal("1"):
        return "75_99_percent"
    return "100_percent"


def _duration_ms(finished_at: float, started_at: float) -> float:
    return round(max(0.0, (finished_at - started_at) * 1000), 3)
