"""Versioned Phase 11 boundary and documentation tests."""

from pathlib import Path

from falcon_api.scenario_simulation import (
    DEFAULT_MONTE_CARLO_TRIALS,
    MAX_CONCURRENT_SCENARIO_SIMULATIONS,
    MAX_DEBT_PAYMENT_ADJUSTMENTS,
    MAX_GOAL_ADJUSTMENTS,
    MAX_SCENARIO_HORIZON_MONTHS,
    MAX_SCENARIOS_PER_REQUEST,
    MAX_MONTE_CARLO_TRIALS,
    MAX_SIMULATIONS_PER_OWNER_WINDOW,
    SCENARIO_COMPARISON_POLICY_VERSION,
    SCENARIO_DECISION_POLICY_VERSION,
    SCENARIO_MONTE_CARLO_POLICY_VERSION,
    SCENARIO_PERSISTENCE_POLICY_VERSION,
    SCENARIO_RISK_POLICY_VERSION,
    SCENARIO_SIMULATION_CONTRACT_VERSION,
    SCENARIO_PATH_POLICY_VERSION,
    SCENARIO_OPERATION_POLICY_VERSION,
    SCENARIO_RATE_WINDOW_SECONDS,
    SCENARIO_REEVALUATION_POLICY_VERSION,
    SCENARIO_SENSITIVITY_POLICY_VERSION,
    SCENARIO_UNCERTAINTY_POLICY_VERSION,
)


def test_scenario_contract_has_stable_limits() -> None:
    assert SCENARIO_SIMULATION_CONTRACT_VERSION == "2026.1"
    assert MAX_SCENARIOS_PER_REQUEST == 10
    assert MAX_SCENARIO_HORIZON_MONTHS == 24
    assert MAX_GOAL_ADJUSTMENTS == 100
    assert MAX_DEBT_PAYMENT_ADJUSTMENTS == 12
    assert SCENARIO_PATH_POLICY_VERSION == "2026.1"
    assert SCENARIO_REEVALUATION_POLICY_VERSION == "2026.1"
    assert SCENARIO_UNCERTAINTY_POLICY_VERSION == "2026.1"
    assert SCENARIO_MONTE_CARLO_POLICY_VERSION == "2026.1"
    assert SCENARIO_RISK_POLICY_VERSION == "2026.1"
    assert SCENARIO_COMPARISON_POLICY_VERSION == "2026.1"
    assert SCENARIO_SENSITIVITY_POLICY_VERSION == "2026.1"
    assert SCENARIO_DECISION_POLICY_VERSION == "2026.1"
    assert SCENARIO_PERSISTENCE_POLICY_VERSION == "2026.1"
    assert DEFAULT_MONTE_CARLO_TRIALS == 1_000
    assert MAX_MONTE_CARLO_TRIALS == 10_000
    assert MAX_CONCURRENT_SCENARIO_SIMULATIONS == 2
    assert MAX_SIMULATIONS_PER_OWNER_WINDOW == 5
    assert SCENARIO_RATE_WINDOW_SECONDS == 60.0
    assert SCENARIO_OPERATION_POLICY_VERSION == "2026.1"


def test_phase_11_documentation_freezes_complete_scope_and_deferrals() -> None:
    document = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "scenarios"
        / "PHASE_11_IMPLEMENTATION.md"
    ).read_text(encoding="utf-8")

    assert "Scenario-simulation contract version: `2026.1`" in document
    assert "Checkpoints 11.0–11.2" in document
    assert "Checkpoint 11.3" in document
    assert "Checkpoint 11.4" in document
    assert "Checkpoint 11.5" in document
    assert "Checkpoint 11.6" in document
    assert "Checkpoint 11.7" in document
    assert "Checkpoint 11.8" in document
    assert "Checkpoint 11.9" in document
    assert "Checkpoint 11.10" in document
    assert "Checkpoint 11.11" in document
    assert "Checkpoint 11.12" in document
    assert "Checkpoint 11.13" in document
    assert "Checkpoint 11.14" in document
    assert "Checkpoint 11.1" in document
    assert "Checkpoint 11.2" in document
    assert "ScenarioEvidenceService.build()" in document
    assert "scenario_source_plan_not_found" in document
    assert "non-negative 95% lower forecast bound" in document
    assert "`gross_income` or\n`total_expense` monthly forecast" in document
    assert "build_deterministic_scenario_paths()" in document
    assert "evaluate_deterministic_scenarios()" in document
    assert "GoalAllocationBound" in document
    assert "calibrate_scenario_uncertainty()" in document
    assert "run_scenario_monte_carlo()" in document
    assert "evaluate_scenario_risk()" in document
    assert "analyze_scenario_decisions()" in document
    assert "ScenarioSimulationRepository.create()" in document
    assert "ScenarioSimulationService.simulate()" in document
    assert "scenario_simulation_runs" in document
    assert "scenario_events" in document
    assert "1,000 trials by default" in document
    assert "hard maximum of 10,000 trials" in document
    assert "`/api/v1/scenario-simulations/{simulation_id}/regenerate`" in document
    assert "at most five generation or regeneration" in document
    assert "privacy-safe monitoring" in document
    assert "Generative explanations and RAG\nbelong to Phase 12" in document
