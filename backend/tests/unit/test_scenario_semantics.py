"""Versioned Phase 11 boundary and documentation tests."""

from pathlib import Path

from falcon_api.scenario_simulation import (
    MAX_GOAL_ADJUSTMENTS,
    MAX_SCENARIO_HORIZON_MONTHS,
    MAX_SCENARIOS_PER_REQUEST,
    SCENARIO_SIMULATION_CONTRACT_VERSION,
)


def test_scenario_contract_has_stable_limits() -> None:
    assert SCENARIO_SIMULATION_CONTRACT_VERSION == "2026.1"
    assert MAX_SCENARIOS_PER_REQUEST == 10
    assert MAX_SCENARIO_HORIZON_MONTHS == 24
    assert MAX_GOAL_ADJUSTMENTS == 100


def test_phase_11_documentation_freezes_batch_1_scope_and_deferrals() -> None:
    document = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "scenarios"
        / "PHASE_11_IMPLEMENTATION.md"
    ).read_text(encoding="utf-8")

    assert "Scenario-simulation contract version: `2026.1`" in document
    assert "Checkpoints 11.0–11.2" in document
    assert "Checkpoint 11.1" in document
    assert "Checkpoint 11.2" in document
    assert "ScenarioEvidenceService.build()" in document
    assert "scenario_source_plan_not_found" in document
    assert "non-negative 95% lower forecast bound" in document
    assert "`gross_income` or\n`total_expense` monthly forecast" in document
    assert "Batch 1 adds no deterministic scenario transformation" in document
    assert "Generative explanations and RAG\nbelong to Phase 12" in document
