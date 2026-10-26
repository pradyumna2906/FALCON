"""Privacy-safe bounded goal-plan monitoring tests."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from falcon_api.goal_planning import (
    GOAL_PLAN_OPERATION_POLICY_VERSION,
    GoalPlanMonitor,
    GoalPlanOperation,
)
from falcon_api.models.enums import GoalPlanStatus
from goal_plan_test_data import transient_goal_plan_run


def test_generation_monitor_emits_only_bounded_operational_evidence() -> None:
    logger = Mock()
    monitor = GoalPlanMonitor(logger=logger, timer=Mock(side_effect=(10.0, 10.125)))
    run = transient_goal_plan_run()

    started = monitor.start()
    monitor.record_generation(
        run,
        operation=GoalPlanOperation.GENERATE,
        started_at=started,
    )

    logger.info.assert_called_once()
    message, = logger.info.call_args.args
    extra = logger.info.call_args.kwargs["extra"]
    assert message == "goal_plan_generation_completed"
    assert extra == {
        "goal_plan_operation_policy_version": GOAL_PLAN_OPERATION_POLICY_VERSION,
        "goal_plan_operation": "generate",
        "goal_plan_goal_count_band": "001_003",
        "goal_plan_horizon_band": "001_003",
        "goal_plan_strategy": "guarded_greedy_fallback",
        "goal_plan_solver_result": "optimal",
        "goal_plan_feasible_count_band": "001_003",
        "goal_plan_at_risk_count_band": "000",
        "goal_plan_utilization_band": "100_percent",
        "goal_plan_reliability": "normal",
        "duration_ms": 125.0,
    }
    serialized = repr(extra).lower()
    for private_value in (
        str(run.user_id),
        str(run.id),
        run.outcomes[0].goal_name.lower(),
        str(run.currency).lower(),
        str(run.allocated_savings),
    ):
        assert private_value.lower() not in serialized


@pytest.mark.parametrize(
    ("allocated", "capacity", "expected"),
    [
        ("0", "0", "none"),
        ("1", "10", "under_25_percent"),
        ("25", "100", "25_49_percent"),
        ("50", "100", "50_74_percent"),
        ("75", "100", "75_99_percent"),
        ("100", "100", "100_percent"),
    ],
)
def test_generation_monitor_buckets_utilization(
    allocated,
    capacity,
    expected,
) -> None:
    logger = Mock()
    run = transient_goal_plan_run()
    run.allocated_savings = Decimal(allocated)
    run.available_savings = Decimal(capacity)

    GoalPlanMonitor(logger=logger, timer=lambda: 1.0).record_generation(
        run,
        operation=GoalPlanOperation.REGENERATE,
        started_at=1.0,
    )

    assert (
        logger.info.call_args.kwargs["extra"]["goal_plan_utilization_band"]
        == expected
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "000"),
        (1, "001_003"),
        (4, "004_010"),
        (11, "011_025"),
        (26, "026_050"),
        (51, "051_plus"),
    ],
)
def test_generation_monitor_buckets_counts(value, expected) -> None:
    logger = Mock()
    run = transient_goal_plan_run()
    run.goal_count = value
    run.feasible_goal_count = value
    run.at_risk_goal_count = 0
    run.uncertain_goal_count = 0

    GoalPlanMonitor(logger=logger, timer=lambda: 1.0).record_generation(
        run,
        operation=GoalPlanOperation.GENERATE,
        started_at=2.0,
    )

    extra = logger.info.call_args.kwargs["extra"]
    assert extra["goal_plan_goal_count_band"] == expected
    assert extra["duration_ms"] == 0.0


@pytest.mark.parametrize(
    "change",
    [
        {"goal_count": -1},
        {"goal_count": False, "feasible_goal_count": False},
        {"at_risk_goal_count": -1},
        {"goal_count": 2},
        {"available_savings": Decimal("NaN")},
        {"allocated_savings": Decimal("-1")},
        {"allocated_savings": Decimal("101")},
        {"strategy": "private-goal-name"},
        {"optimizer_status": "private-solver-output"},
        {"forecast_reliability": "private"},
    ],
)
def test_generation_monitor_rejects_unbounded_or_inconsistent_fields(change) -> None:
    run = transient_goal_plan_run()
    for name, value in change.items():
        setattr(run, name, value)

    with pytest.raises(ValueError):
        GoalPlanMonitor(logger=Mock(), timer=lambda: 1.0).record_generation(
            run,
            operation=GoalPlanOperation.GENERATE,
            started_at=1.0,
        )


def test_generation_monitor_rejects_transition_operation() -> None:
    with pytest.raises(ValueError, match="generation telemetry"):
        GoalPlanMonitor(logger=Mock()).record_generation(
            transient_goal_plan_run(),
            operation=GoalPlanOperation.APPROVE,
            started_at=0.0,
        )


@pytest.mark.parametrize(
    ("operation", "status"),
    [
        (GoalPlanOperation.APPROVE, GoalPlanStatus.APPROVED),
        (GoalPlanOperation.REJECT, GoalPlanStatus.REJECTED),
    ],
)
def test_transition_monitor_logs_only_operation_status_and_duration(
    operation,
    status,
) -> None:
    logger = Mock()
    GoalPlanMonitor(logger=logger, timer=lambda: 2.25).record_transition(
        operation=operation,
        status=status,
        started_at=2.0,
    )

    assert logger.info.call_args.args == ("goal_plan_transition_completed",)
    assert logger.info.call_args.kwargs["extra"] == {
        "goal_plan_operation_policy_version": "2026.1",
        "goal_plan_operation": operation.value,
        "goal_plan_status": status.value,
        "duration_ms": 250.0,
    }


def test_transition_monitor_rejects_inconsistent_operation_and_status() -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        GoalPlanMonitor(logger=Mock()).record_transition(
            operation=GoalPlanOperation.APPROVE,
            status=GoalPlanStatus.REJECTED,
            started_at=0.0,
        )
