"""Checkpoint 11.7 bounded seeded Monte Carlo simulation tests."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from falcon_api.scenario_simulation import (
    MAX_MONTE_CARLO_SEED,
    MAX_MONTE_CARLO_TRIALS,
    MONTE_CARLO_ALLOCATION_METHOD,
    MONTE_CARLO_PROBABILITY_METHOD,
    MonteCarloConfig,
    OneTimeExpenseAssumption,
    ScenarioAssumptions,
    ScenarioMonteCarloStatus,
    ScenarioReasonCode,
    build_deterministic_scenario_paths,
    calibrate_scenario_uncertainty,
    evaluate_deterministic_scenarios,
    run_scenario_monte_carlo,
)
from goal_plan_test_data import ZeroSolver
from scenario_test_data import transient_scenario_snapshot


def _scenario(amount: str = "25") -> ScenarioAssumptions:
    return ScenarioAssumptions(
        name="Expense shock",
        one_time_expenses=(
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal(amount),
            ),
        ),
    )


@pytest.mark.parametrize(
    "config",
    [
        lambda: MonteCarloConfig(trial_count=0),
        lambda: MonteCarloConfig(trial_count=MAX_MONTE_CARLO_TRIALS + 1),
        lambda: MonteCarloConfig(trial_count=True),
        lambda: MonteCarloConfig(seed=-1),
        lambda: MonteCarloConfig(seed=MAX_MONTE_CARLO_SEED + 1),
        lambda: MonteCarloConfig(seed=True),
    ],
)
def test_monte_carlo_configuration_is_strictly_bounded(config) -> None:
    with pytest.raises(ValueError, match="Monte Carlo"):
        config()


def test_seeded_simulation_is_replayable_bounded_and_order_independent() -> None:
    snapshot = transient_scenario_snapshot((_scenario(),))
    config = MonteCarloConfig(trial_count=256, seed=42)

    first = run_scenario_monte_carlo(snapshot, config=config, solver=ZeroSolver())
    second = run_scenario_monte_carlo(snapshot, config=config, solver=ZeroSolver())
    changed = run_scenario_monte_carlo(
        snapshot,
        config=MonteCarloConfig(trial_count=256, seed=43),
        solver=ZeroSolver(),
    )

    assert first == second
    assert first[0].sample_digest != changed[0].sample_digest
    assert len({item.scenario_seed for item in first}) == 1
    for result in first:
        assert result.status is ScenarioMonteCarloStatus.COMPLETED
        assert result.trial_count == 256
        assert result.probability_method == MONTE_CARLO_PROBABILITY_METHOD
        assert result.allocation_method == MONTE_CARLO_ALLOCATION_METHOD
        assert len(result.capacity_totals) == 256 * 8
        assert len(result.negative_savings) == 256
        assert len(result.goal_samples[0].completion_steps) == 256 * 2
        assert len(result.goal_samples[0].final_shortfalls) == 256 * 8
    totals = np.frombuffer(first[0].capacity_totals, dtype="<f8")
    assert bool(np.all(np.isfinite(totals)))
    assert bool(np.all((totals >= 100) & (totals <= 200)))


def test_default_and_maximum_trial_counts_remain_supported() -> None:
    snapshot = transient_scenario_snapshot((_scenario(),))
    default = run_scenario_monte_carlo(
        snapshot,
        solver=ZeroSolver(),
    )[0]
    assert default.trial_count == 1_000

    paths = build_deterministic_scenario_paths(snapshot)
    calibrations = calibrate_scenario_uncertainty(snapshot, paths=paths)
    evaluations = evaluate_deterministic_scenarios(snapshot, solver=ZeroSolver())
    maximum = run_scenario_monte_carlo(
        snapshot,
        config=MonteCarloConfig(trial_count=MAX_MONTE_CARLO_TRIALS, seed=7),
        solver=ZeroSolver(),
        paths=paths[:1],
        calibrations=calibrations[:1],
        evaluations=evaluations[:1],
    )[0]

    assert maximum.trial_count == 10_000
    assert len(maximum.capacity_totals) == 10_000 * 8


def test_conservative_fallback_is_a_replayable_protected_point_mass() -> None:
    snapshot = transient_scenario_snapshot((_scenario(),))
    assert snapshot.forecast is not None
    snapshot = replace(
        snapshot,
        forecast=replace(snapshot.forecast, calibration_residual_count=0),
    )

    result = run_scenario_monte_carlo(
        snapshot,
        config=MonteCarloConfig(trial_count=32, seed=5),
        solver=ZeroSolver(),
    )[1]

    assert result.status is ScenarioMonteCarloStatus.CONSERVATIVE_FALLBACK
    totals = np.frombuffer(result.capacity_totals, dtype="<f8")
    assert set(totals) == {100.0}
    assert (
        ScenarioReasonCode.CONSERVATIVE_PROTECTED_FALLBACK
        in result.reason_codes
    )


def test_unavailable_and_blocked_paths_never_emit_trial_samples() -> None:
    assumption = ScenarioAssumptions(
        name="Missing income",
        income_change_percent=Decimal("-10"),
    )
    missing = transient_scenario_snapshot(
        (assumption,),
        include_supplemental=False,
    )
    unavailable = run_scenario_monte_carlo(
        missing,
        config=MonteCarloConfig(trial_count=16, seed=1),
        solver=ZeroSolver(),
    )[3]
    assert unavailable.status is ScenarioMonteCarloStatus.UNAVAILABLE
    assert unavailable.trial_count == 0
    assert unavailable.capacity_totals == b""

    available = transient_scenario_snapshot((assumption,))
    blocked = replace(
        available,
        source_plan=replace(available.source_plan, strategy="blocked"),
    )
    blocked_result = run_scenario_monte_carlo(
        blocked,
        config=MonteCarloConfig(trial_count=16, seed=1),
        solver=ZeroSolver(),
    )[0]
    assert blocked_result.status is ScenarioMonteCarloStatus.BLOCKED
    assert blocked_result.trial_count == 0


def test_negative_raw_savings_is_measured_before_safe_allocation_clipping() -> None:
    snapshot = transient_scenario_snapshot((_scenario("75"),))

    result = run_scenario_monte_carlo(
        snapshot,
        config=MonteCarloConfig(trial_count=512, seed=9),
        solver=ZeroSolver(),
    )[3]

    negative = np.frombuffer(result.negative_savings, dtype=np.uint8)
    capacity = np.frombuffer(result.capacity_totals, dtype="<f8")
    assert 0 < int(np.count_nonzero(negative)) < 512
    assert bool(np.all(capacity >= 0))


def test_mismatched_inputs_and_excessive_work_are_rejected(monkeypatch) -> None:
    snapshot = transient_scenario_snapshot((_scenario(),))
    paths = build_deterministic_scenario_paths(snapshot)
    calibrations = calibrate_scenario_uncertainty(snapshot, paths=paths)
    evaluations = evaluate_deterministic_scenarios(snapshot, solver=ZeroSolver())

    with pytest.raises(ValueError, match="same scenario paths"):
        run_scenario_monte_carlo(
            snapshot,
            paths=paths,
            calibrations=calibrations[:-1],
            evaluations=evaluations,
        )

    malformed = (
        replace(calibrations[0], points=calibrations[0].points[:-1]),
        *calibrations[1:],
    )
    with pytest.raises(ValueError, match="periods must match"):
        run_scenario_monte_carlo(
            snapshot,
            paths=paths,
            calibrations=malformed,
            evaluations=evaluations,
        )

    monkeypatch.setattr(
        "falcon_api.scenario_simulation.monte_carlo.MAX_MONTE_CARLO_WORK_UNITS",
        1,
    )
    with pytest.raises(ValueError, match="work budget"):
        run_scenario_monte_carlo(
            snapshot,
            config=MonteCarloConfig(trial_count=2),
            paths=paths,
            calibrations=calibrations,
            evaluations=evaluations,
        )
