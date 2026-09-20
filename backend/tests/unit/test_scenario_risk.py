"""Checkpoint 11.8 empirical probability, tail-risk, and robustness tests."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from falcon_api.scenario_simulation import (
    DETERMINISTIC_PROBABILITY_METHOD,
    EMPIRICAL_PERCENTILE_METHOD,
    GoalScenarioAdjustment,
    MONTE_CARLO_PROBABILITY_METHOD,
    MonteCarloConfig,
    OneTimeExpenseAssumption,
    ScenarioAssumptions,
    ScenarioCalibrationReliability,
    ScenarioRiskStatus,
    evaluate_scenario_risk,
)
from goal_plan_test_data import GOAL_ID, ZeroSolver
from scenario_test_data import transient_scenario_snapshot


def _expense_case(amount: str) -> ScenarioAssumptions:
    return ScenarioAssumptions(
        name=f"Expense {amount}",
        one_time_expenses=(
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal(amount),
            ),
        ),
    )


def test_risk_metrics_are_replayable_bounded_and_method_explicit() -> None:
    snapshot = transient_scenario_snapshot((_expense_case("75"),))
    config = MonteCarloConfig(trial_count=512, seed=123)

    first = evaluate_scenario_risk(snapshot, config=config, solver=ZeroSolver())
    second = evaluate_scenario_risk(snapshot, config=config, solver=ZeroSolver())

    assert first == second
    result = first[3]
    assert result.status is ScenarioRiskStatus.AVAILABLE
    assert result.reliability is ScenarioCalibrationReliability.NORMAL
    assert result.trial_count == 512
    assert result.probability_method == MONTE_CARLO_PROBABILITY_METHOD
    assert result.deterministic_probability_method == DETERMINISTIC_PROBABILITY_METHOD
    assert result.percentile_method == EMPIRICAL_PERCENTILE_METHOD
    probabilities = (
        result.all_goals_completion_probability,
        result.all_deadlines_met_probability,
        result.emergency_reserve_coverage_probability,
        result.negative_savings_probability,
        result.constraint_feasibility_probability,
    )
    assert all(value is not None and 0 <= value <= 1 for value in probabilities)
    assert result.negative_savings_probability is not None
    assert Decimal("0") < result.negative_savings_probability < Decimal("1")
    assert result.capacity_p10 <= result.capacity_p50 <= result.capacity_p90
    assert (
        result.total_shortfall_p10
        <= result.total_shortfall_p50
        <= result.total_shortfall_p90
    )
    assert result.tail_shortfall_var_90 == result.total_shortfall_p90
    assert result.tail_expected_shortfall_90 >= result.tail_shortfall_var_90
    assert Decimal("0") <= result.robustness_score <= Decimal("100")


def test_goal_metrics_report_unconditional_and_conditional_denominators() -> None:
    snapshot = transient_scenario_snapshot((_expense_case("75"),))

    goal = evaluate_scenario_risk(
        snapshot,
        config=MonteCarloConfig(trial_count=400, seed=3),
        solver=ZeroSolver(),
    )[3].goals[0]

    assert goal.completion_denominator == 400
    assert goal.deadline_denominator == 400
    assert goal.completion_period_denominator == goal.completion_count
    assert goal.completion_count == int(goal.completion_probability * 400)
    assert goal.deadline_met_count == int(goal.deadline_met_probability * 400)
    assert goal.completion_period_p10 is not None
    assert (
        goal.completion_period_p10
        <= goal.completion_period_p50
        <= goal.completion_period_p90
    )
    assert goal.shortfall_p10 <= goal.shortfall_p50 <= goal.shortfall_p90
    assert goal.deterministic_completion_probability is not None
    assert goal.completion_probability_delta == (
        goal.completion_probability - goal.deterministic_completion_probability
    )


def test_easy_plan_is_fully_robust_and_reserve_risk_is_empirical() -> None:
    snapshot = transient_scenario_snapshot((_expense_case("1"),))
    easy = evaluate_scenario_risk(
        snapshot,
        config=MonteCarloConfig(trial_count=256, seed=8),
        solver=ZeroSolver(),
    )[0]

    assert easy.all_goals_completion_probability == Decimal("1.000000")
    assert easy.all_deadlines_met_probability == Decimal("1.000000")
    assert easy.emergency_reserve_coverage_probability == Decimal("1.000000")
    assert easy.negative_savings_probability == Decimal("0.000000")
    assert easy.constraint_feasibility_probability == Decimal("1.000000")
    assert easy.robustness_score == Decimal("100.0000")

    references = evaluate_scenario_risk(
        snapshot,
        config=MonteCarloConfig(trial_count=256, seed=8),
        solver=ZeroSolver(),
    )[:3]
    assert len({item.expected_capacity for item in references}) == 1
    assert len({item.all_goals_completion_probability for item in references}) == 1

    reserved = replace(
        snapshot,
        source_plan=replace(
            snapshot.source_plan,
            emergency_reserve_amount=Decimal("120.0000"),
        ),
    )
    reserve_risk = evaluate_scenario_risk(
        reserved,
        config=MonteCarloConfig(trial_count=512, seed=8),
        solver=ZeroSolver(),
    )[0]
    assert reserve_risk.emergency_reserve_coverage_probability is not None
    assert (
        Decimal("0")
        < reserve_risk.emergency_reserve_coverage_probability
        < Decimal("1")
    )
    assert reserve_risk.robustness_score < Decimal("100")


def test_provisional_and_conservative_outputs_remain_explicitly_limited() -> None:
    snapshot = transient_scenario_snapshot((_expense_case("25"),))
    assert snapshot.forecast is not None
    provisional_snapshot = replace(
        snapshot,
        forecast=replace(
            snapshot.forecast,
            uncertainty_reliability="provisional",
            calibration_residual_count=2,
        ),
    )
    provisional = evaluate_scenario_risk(
        provisional_snapshot,
        config=MonteCarloConfig(trial_count=32, seed=2),
        solver=ZeroSolver(),
    )[0]
    assert provisional.status is ScenarioRiskStatus.LIMITED
    assert provisional.reliability is ScenarioCalibrationReliability.PROVISIONAL

    conservative_snapshot = replace(
        snapshot,
        forecast=replace(snapshot.forecast, calibration_residual_count=0),
    )
    conservative = evaluate_scenario_risk(
        conservative_snapshot,
        config=MonteCarloConfig(trial_count=32, seed=2),
        solver=ZeroSolver(),
    )[0]
    assert conservative.status is ScenarioRiskStatus.LIMITED
    assert conservative.reliability is ScenarioCalibrationReliability.CONSERVATIVE
    assert conservative.capacity_p10 == conservative.capacity_p90


def test_unavailable_and_blocked_risk_contains_no_invented_statistics() -> None:
    assumption = ScenarioAssumptions(
        name="Missing income",
        income_change_percent=Decimal("-10"),
    )
    missing = transient_scenario_snapshot(
        (assumption,),
        include_supplemental=False,
    )
    unavailable = evaluate_scenario_risk(
        missing,
        config=MonteCarloConfig(trial_count=16, seed=1),
        solver=ZeroSolver(),
    )[3]
    assert unavailable.status is ScenarioRiskStatus.UNAVAILABLE
    assert unavailable.trial_count == 0
    assert unavailable.all_goals_completion_probability is None
    assert unavailable.goals == ()

    available = transient_scenario_snapshot((assumption,))
    blocked = replace(
        available,
        source_plan=replace(available.source_plan, strategy="blocked"),
    )
    blocked_result = evaluate_scenario_risk(
        blocked,
        config=MonteCarloConfig(trial_count=16, seed=1),
        solver=ZeroSolver(),
    )[0]
    assert blocked_result.status is ScenarioRiskStatus.BLOCKED
    assert blocked_result.expected_total_shortfall is None


def test_seed_change_changes_empirical_risk_identity() -> None:
    snapshot = transient_scenario_snapshot((_expense_case("75"),))

    first = evaluate_scenario_risk(
        snapshot,
        config=MonteCarloConfig(trial_count=128, seed=1),
        solver=ZeroSolver(),
    )[3]
    second = evaluate_scenario_risk(
        snapshot,
        config=MonteCarloConfig(trial_count=128, seed=2),
        solver=ZeroSolver(),
    )[3]

    assert first.risk_id != second.risk_id


def test_goal_completion_period_is_none_when_no_trial_completes() -> None:
    never_funded = ScenarioAssumptions(
        name="No capacity",
        one_time_expenses=(
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal("75"),
            ),
        ),
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                target_amount=Decimal("200"),
            ),
        ),
    )
    snapshot = transient_scenario_snapshot((never_funded,))

    goal = evaluate_scenario_risk(
        snapshot,
        config=MonteCarloConfig(trial_count=32, seed=4),
        solver=ZeroSolver(),
    )[3].goals[0]

    assert goal.completion_count == 0
    assert goal.completion_period_denominator == 0
    assert goal.completion_period_p10 is None
    assert goal.completion_period_p50 is None
    assert goal.completion_period_p90 is None
