"""Checkpoint 11.9-11.10 comparison and decision-ranking tests."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from falcon_api.scenario_simulation import (
    GoalScenarioAdjustment,
    MonteCarloConfig,
    OneTimeExpenseAssumption,
    ScenarioAssumptions,
    ScenarioCaseKind,
    ScenarioComparisonStatus,
    ScenarioDecisionReasonCode,
    analyze_scenario_decisions,
    validate_scenario_decision_analysis,
)
from goal_plan_test_data import GOAL_ID, ZeroSolver
from scenario_test_data import transient_scenario_snapshot


def _expense_case(amount: str = "75") -> ScenarioAssumptions:
    return ScenarioAssumptions(
        name=f"Expense {amount}",
        one_time_expenses=(
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal(amount),
            ),
        ),
    )


def _analyze(*scenarios: ScenarioAssumptions):
    snapshot = transient_scenario_snapshot(tuple(scenarios))
    analysis = analyze_scenario_decisions(
        snapshot,
        config=MonteCarloConfig(trial_count=64, seed=11),
        solver=ZeroSolver(),
    )
    return snapshot, analysis


def test_decisions_are_replayable_ranked_and_protect_equal_baseline() -> None:
    snapshot, first = _analyze(_expense_case())
    second = analyze_scenario_decisions(
        snapshot,
        config=MonteCarloConfig(trial_count=64, seed=11),
        solver=ZeroSolver(),
    )

    assert first == second
    assert first.trial_count == 64
    assert first.root_seed == 11
    assert tuple(item.rank for item in first.alternatives) == (1, 2, 3, 4)
    recommended = next(item for item in first.alternatives if item.recommended)
    assert recommended.path.kind is ScenarioCaseKind.PROTECTED
    assert recommended.path.path_id == first.baseline_path_id
    assert recommended.path.path_id == first.recommended_path_id
    assert ScenarioDecisionReasonCode.RECOMMENDED_ALTERNATIVE in recommended.reason_codes
    validate_scenario_decision_analysis(snapshot=snapshot, analysis=first)


def test_harmful_expense_is_compared_and_dominated_without_false_precision() -> None:
    _, analysis = _analyze(_expense_case())
    expense = next(
        item
        for item in analysis.alternatives
        if item.path.kind is ScenarioCaseKind.USER_DEFINED
    )

    assert expense.status is ScenarioComparisonStatus.AVAILABLE
    assert expense.expected_capacity_delta is not None
    assert expense.expected_capacity_delta < 0
    assert expense.dominated_by_path_id is not None
    assert not expense.recommended
    assert ScenarioDecisionReasonCode.DOMINATED_ALTERNATIVE in expense.reason_codes
    assert expense.sensitivity_signals[0].factor == "one_time_expense"
    assert expense.sensitivity_signals[0].direct_capacity_effect == Decimal("-75.0000")
    assert sum(
        (item.influence_score for item in expense.sensitivity_signals),
        Decimal("0"),
    ) == Decimal("100.0000")


def test_sensitivity_is_bounded_noncausal_and_multi_factor() -> None:
    case = ScenarioAssumptions(
        name="Combined pressure",
        income_change_percent=Decimal("-10"),
        expense_change_percent=Decimal("5"),
        one_time_expenses=(
            OneTimeExpenseAssumption(date(2026, 10, 1), Decimal("20")),
        ),
    )
    _, analysis = _analyze(case)
    alternative = next(
        item
        for item in analysis.alternatives
        if item.path.kind is ScenarioCaseKind.USER_DEFINED
    )

    assert {item.factor for item in alternative.sensitivity_signals} == {
        "income",
        "expense",
        "one_time_expense",
    }
    assert all(
        item.method == "direct_effect_plus_equal_outcome_attribution"
        for item in alternative.sensitivity_signals
    )
    assert sum(
        (item.influence_score for item in alternative.sensitivity_signals),
        Decimal("0"),
    ) == pytest.approx(Decimal("100"), abs=Decimal("0.001"))


def test_added_contribution_excludes_paused_months() -> None:
    case = ScenarioAssumptions(
        name="Contribution alternative",
        goal_adjustments=(
            GoalScenarioAdjustment(
                goal_id=GOAL_ID,
                monthly_contribution_delta=Decimal("10"),
                pause_start=date(2026, 11, 1),
                pause_end=date(2026, 11, 1),
            ),
        ),
    )
    _, analysis = _analyze(case)
    alternative = next(
        item
        for item in analysis.alternatives
        if item.path.kind is ScenarioCaseKind.USER_DEFINED
    )

    assert alternative.additional_required_contribution == Decimal("10.0000")
    assert (
        ScenarioDecisionReasonCode.ADDED_CONTRIBUTION_REQUIRED
        in alternative.reason_codes
    )


def test_mutated_decision_identity_is_rejected_before_storage() -> None:
    snapshot, analysis = _analyze(_expense_case())

    with pytest.raises(ValueError, match="identity"):
        validate_scenario_decision_analysis(
            snapshot=snapshot,
            analysis=replace(analysis, analysis_id="0" * 64),
        )

    changed = replace(
        analysis.alternatives[0],
        decision_score=Decimal("99.0000"),
    )
    with pytest.raises(ValueError, match="inconsistent"):
        validate_scenario_decision_analysis(
            snapshot=snapshot,
            analysis=replace(
                analysis,
                alternatives=(changed, *analysis.alternatives[1:]),
            ),
        )
