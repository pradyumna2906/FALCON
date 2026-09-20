"""Empirical Phase 11 completion, downside, and robustness risk metrics."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID

import numpy as np

from falcon_api.analytics.types import money
from falcon_api.goal_planning.optimizer import LinearProgramSolver
from falcon_api.scenario_simulation.calibration import (
    ScenarioUncertaintyCalibration,
    calibrate_scenario_uncertainty,
)
from falcon_api.scenario_simulation.evaluation import (
    DeterministicScenarioEvaluation,
    evaluate_deterministic_scenarios,
)
from falcon_api.scenario_simulation.monte_carlo import (
    MonteCarloConfig,
    ScenarioGoalTrialSamples,
    ScenarioMonteCarloSimulation,
    run_scenario_monte_carlo,
)
from falcon_api.scenario_simulation.paths import build_deterministic_scenario_paths
from falcon_api.scenario_simulation.semantics import (
    SCENARIO_RISK_POLICY_VERSION,
    ScenarioCalibrationReliability,
    ScenarioMonteCarloStatus,
    ScenarioReasonCode,
    ScenarioRiskStatus,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceSnapshot


DETERMINISTIC_PROBABILITY_METHOD = "phase_10_analytical_normal_cdf"
EMPIRICAL_PERCENTILE_METHOD = "nearest_rank_empirical"
TAIL_RISK_LEVEL = Decimal("0.900000")
_PROBABILITY_QUANTUM = Decimal("0.000001")
_SCORE_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class ScenarioGoalRiskMetrics:
    """Per-goal empirical outcomes with explicit conditional denominators."""

    goal_id: UUID
    rank: int
    completion_count: int
    completion_denominator: int
    completion_probability: Decimal
    deadline_met_count: int
    deadline_denominator: int
    deadline_met_probability: Decimal
    completion_period_denominator: int
    completion_period_p10: date | None
    completion_period_p50: date | None
    completion_period_p90: date | None
    expected_shortfall: Decimal
    shortfall_p10: Decimal
    shortfall_p50: Decimal
    shortfall_p90: Decimal
    deterministic_completion_probability: Decimal | None
    completion_probability_delta: Decimal | None


@dataclass(frozen=True, slots=True)
class ScenarioRiskMetrics:
    """Bounded aggregate risk view for one deterministic scenario alternative."""

    risk_id: str
    snapshot_id: str
    path_id: str
    simulation_id: str
    policy_version: str
    status: ScenarioRiskStatus
    reliability: ScenarioCalibrationReliability
    trial_count: int
    seed: int
    probability_method: str
    deterministic_probability_method: str
    percentile_method: str
    all_goals_completion_probability: Decimal | None
    all_deadlines_met_probability: Decimal | None
    emergency_reserve_coverage_probability: Decimal | None
    negative_savings_probability: Decimal | None
    constraint_feasibility_probability: Decimal | None
    expected_capacity: Decimal | None
    capacity_p10: Decimal | None
    capacity_p50: Decimal | None
    capacity_p90: Decimal | None
    expected_total_shortfall: Decimal | None
    total_shortfall_p10: Decimal | None
    total_shortfall_p50: Decimal | None
    total_shortfall_p90: Decimal | None
    tail_shortfall_var_90: Decimal | None
    tail_expected_shortfall_90: Decimal | None
    robustness_score: Decimal | None
    goals: tuple[ScenarioGoalRiskMetrics, ...]
    reason_codes: tuple[ScenarioReasonCode, ...]


def evaluate_scenario_risk(
    snapshot: ScenarioEvidenceSnapshot,
    *,
    config: MonteCarloConfig | None = None,
    solver: LinearProgramSolver | None = None,
) -> tuple[ScenarioRiskMetrics, ...]:
    """Execute calibration, seeded replay, and exact empirical reduction."""
    paths = build_deterministic_scenario_paths(snapshot)
    calibrations = calibrate_scenario_uncertainty(snapshot, paths=paths)
    evaluations = evaluate_deterministic_scenarios(snapshot, solver=solver)
    simulations = run_scenario_monte_carlo(
        snapshot,
        config=config,
        solver=solver,
        paths=paths,
        calibrations=calibrations,
        evaluations=evaluations,
    )
    return tuple(
        _risk_metrics(
            snapshot=snapshot,
            calibration=calibration,
            evaluation=evaluation,
            simulation=simulation,
        )
        for calibration, evaluation, simulation in zip(
            calibrations,
            evaluations,
            simulations,
            strict=True,
        )
    )


def _risk_metrics(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    calibration: ScenarioUncertaintyCalibration,
    evaluation: DeterministicScenarioEvaluation,
    simulation: ScenarioMonteCarloSimulation,
) -> ScenarioRiskMetrics:
    if simulation.status in {
        ScenarioMonteCarloStatus.BLOCKED,
        ScenarioMonteCarloStatus.UNAVAILABLE,
    }:
        status = (
            ScenarioRiskStatus.BLOCKED
            if simulation.status is ScenarioMonteCarloStatus.BLOCKED
            else ScenarioRiskStatus.UNAVAILABLE
        )
        return _empty_risk(
            calibration=calibration,
            simulation=simulation,
            status=status,
        )

    trial_count = simulation.trial_count
    capacity = _float64(simulation.capacity_totals, trial_count)
    shortfalls = _float64(simulation.total_shortfalls, trial_count)
    negative = _boolean(simulation.negative_savings, trial_count)
    reserve = _boolean(simulation.reserve_covered, trial_count)
    feasible = _boolean(simulation.constraint_feasible, trial_count)
    all_completed = _boolean(simulation.all_goals_completed, trial_count)
    all_deadlines = _boolean(simulation.all_deadlines_met, trial_count)
    _finite(capacity, shortfalls)
    goal_evidence = {item.goal_id: item for item in evaluation.goals}
    periods = tuple(item.period_start for item in calibration.points)
    goals = tuple(
        _goal_metrics(
            samples=samples,
            deterministic=goal_evidence[samples.goal_id],
            periods=periods,
            local_date=snapshot.local_date,
            trial_count=trial_count,
        )
        for samples in simulation.goal_samples
    )
    all_goals_probability = _probability(all_completed)
    deadlines_probability = _probability(all_deadlines)
    reserve_probability = _probability(reserve)
    negative_probability = _probability(negative)
    feasible_probability = _probability(feasible)
    capacity_percentiles = _money_percentiles(capacity)
    shortfall_percentiles = _money_percentiles(shortfalls)
    tail_var_raw = _nearest_rank(shortfalls, float(TAIL_RISK_LEVEL))
    tail_var = money(Decimal(str(tail_var_raw)))
    tail_mask = shortfalls + 1e-12 >= float(tail_var_raw)
    tail_expected = _money_mean(shortfalls[tail_mask])
    robustness = _robustness_score(
        all_goals=all_goals_probability,
        deadlines=deadlines_probability,
        reserve=reserve_probability,
        no_negative=Decimal("1") - negative_probability,
        feasible=feasible_probability,
    )
    status = (
        ScenarioRiskStatus.AVAILABLE
        if calibration.reliability is ScenarioCalibrationReliability.NORMAL
        and simulation.status is ScenarioMonteCarloStatus.COMPLETED
        else ScenarioRiskStatus.LIMITED
    )
    values = {
        "snapshot_id": simulation.snapshot_id,
        "path_id": simulation.path_id,
        "simulation_id": simulation.simulation_id,
        "policy_version": SCENARIO_RISK_POLICY_VERSION,
        "status": status,
        "reliability": calibration.reliability,
        "trial_count": trial_count,
        "seed": simulation.root_seed,
        "all_goals_completion_probability": all_goals_probability,
        "all_deadlines_met_probability": deadlines_probability,
        "emergency_reserve_coverage_probability": reserve_probability,
        "negative_savings_probability": negative_probability,
        "constraint_feasibility_probability": feasible_probability,
        "expected_capacity": _money_mean(capacity),
        "capacity_p10": capacity_percentiles[0],
        "capacity_p50": capacity_percentiles[1],
        "capacity_p90": capacity_percentiles[2],
        "expected_total_shortfall": _money_mean(shortfalls),
        "total_shortfall_p10": shortfall_percentiles[0],
        "total_shortfall_p50": shortfall_percentiles[1],
        "total_shortfall_p90": shortfall_percentiles[2],
        "tail_shortfall_var_90": tail_var,
        "tail_expected_shortfall_90": tail_expected,
        "robustness_score": robustness,
        "goals": goals,
        "reasons": simulation.reason_codes,
    }
    return ScenarioRiskMetrics(
        risk_id=_hash(values),
        snapshot_id=simulation.snapshot_id,
        path_id=simulation.path_id,
        simulation_id=simulation.simulation_id,
        policy_version=SCENARIO_RISK_POLICY_VERSION,
        status=status,
        reliability=calibration.reliability,
        trial_count=trial_count,
        seed=simulation.root_seed,
        probability_method=simulation.probability_method,
        deterministic_probability_method=DETERMINISTIC_PROBABILITY_METHOD,
        percentile_method=EMPIRICAL_PERCENTILE_METHOD,
        all_goals_completion_probability=all_goals_probability,
        all_deadlines_met_probability=deadlines_probability,
        emergency_reserve_coverage_probability=reserve_probability,
        negative_savings_probability=negative_probability,
        constraint_feasibility_probability=feasible_probability,
        expected_capacity=values["expected_capacity"],
        capacity_p10=capacity_percentiles[0],
        capacity_p50=capacity_percentiles[1],
        capacity_p90=capacity_percentiles[2],
        expected_total_shortfall=values["expected_total_shortfall"],
        total_shortfall_p10=shortfall_percentiles[0],
        total_shortfall_p50=shortfall_percentiles[1],
        total_shortfall_p90=shortfall_percentiles[2],
        tail_shortfall_var_90=tail_var,
        tail_expected_shortfall_90=tail_expected,
        robustness_score=robustness,
        goals=goals,
        reason_codes=simulation.reason_codes,
    )


def _goal_metrics(
    *,
    samples: ScenarioGoalTrialSamples,
    deterministic: Any,
    periods: tuple[date, ...],
    local_date: date,
    trial_count: int,
) -> ScenarioGoalRiskMetrics:
    completion_steps = _int16(samples.completion_steps, trial_count)
    shortfalls = _float64(samples.final_shortfalls, trial_count)
    deadline_met = _boolean(samples.deadline_met, trial_count)
    _finite(shortfalls)
    completed = completion_steps >= 0
    completion_count = int(np.count_nonzero(completed))
    completion_probability = _probability(completed)
    deadline_count = int(np.count_nonzero(deadline_met))
    deadline_probability = _probability(deadline_met)
    completed_steps = completion_steps[completed]
    period_percentiles = tuple(
        _completion_period(
            step=_nearest_rank(completed_steps, quantile),
            periods=periods,
            local_date=local_date,
        )
        if completion_count
        else None
        for quantile in (0.10, 0.50, 0.90)
    )
    shortfall_percentiles = _money_percentiles(shortfalls)
    deterministic_probability = deterministic.completion_probability
    delta = (
        (completion_probability - deterministic_probability).quantize(
            _PROBABILITY_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )
        if deterministic_probability is not None
        else None
    )
    return ScenarioGoalRiskMetrics(
        goal_id=samples.goal_id,
        rank=samples.rank,
        completion_count=completion_count,
        completion_denominator=trial_count,
        completion_probability=completion_probability,
        deadline_met_count=deadline_count,
        deadline_denominator=trial_count,
        deadline_met_probability=deadline_probability,
        completion_period_denominator=completion_count,
        completion_period_p10=period_percentiles[0],
        completion_period_p50=period_percentiles[1],
        completion_period_p90=period_percentiles[2],
        expected_shortfall=_money_mean(shortfalls),
        shortfall_p10=shortfall_percentiles[0],
        shortfall_p50=shortfall_percentiles[1],
        shortfall_p90=shortfall_percentiles[2],
        deterministic_completion_probability=deterministic_probability,
        completion_probability_delta=delta,
    )


def _empty_risk(
    *,
    calibration: ScenarioUncertaintyCalibration,
    simulation: ScenarioMonteCarloSimulation,
    status: ScenarioRiskStatus,
) -> ScenarioRiskMetrics:
    values = {
        "snapshot_id": simulation.snapshot_id,
        "path_id": simulation.path_id,
        "simulation_id": simulation.simulation_id,
        "policy_version": SCENARIO_RISK_POLICY_VERSION,
        "status": status,
        "reliability": calibration.reliability,
        "seed": simulation.root_seed,
        "reasons": simulation.reason_codes,
    }
    return ScenarioRiskMetrics(
        risk_id=_hash(values),
        snapshot_id=simulation.snapshot_id,
        path_id=simulation.path_id,
        simulation_id=simulation.simulation_id,
        policy_version=SCENARIO_RISK_POLICY_VERSION,
        status=status,
        reliability=calibration.reliability,
        trial_count=0,
        seed=simulation.root_seed,
        probability_method=simulation.probability_method,
        deterministic_probability_method=DETERMINISTIC_PROBABILITY_METHOD,
        percentile_method=EMPIRICAL_PERCENTILE_METHOD,
        all_goals_completion_probability=None,
        all_deadlines_met_probability=None,
        emergency_reserve_coverage_probability=None,
        negative_savings_probability=None,
        constraint_feasibility_probability=None,
        expected_capacity=None,
        capacity_p10=None,
        capacity_p50=None,
        capacity_p90=None,
        expected_total_shortfall=None,
        total_shortfall_p10=None,
        total_shortfall_p50=None,
        total_shortfall_p90=None,
        tail_shortfall_var_90=None,
        tail_expected_shortfall_90=None,
        robustness_score=None,
        goals=(),
        reason_codes=simulation.reason_codes,
    )


def _probability(values: np.ndarray) -> Decimal:
    if values.size == 0:
        raise ValueError("Empirical probabilities require at least one trial.")
    count = int(np.count_nonzero(values))
    return (Decimal(count) / Decimal(values.size)).quantize(
        _PROBABILITY_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _money_percentiles(values: np.ndarray) -> tuple[Decimal, Decimal, Decimal]:
    return tuple(
        money(Decimal(str(_nearest_rank(values, quantile))))
        for quantile in (0.10, 0.50, 0.90)
    )


def _nearest_rank(values: np.ndarray, quantile: float) -> float | int:
    if values.size == 0:
        raise ValueError("Empirical percentiles require at least one observation.")
    ordered = np.sort(values)
    index = max(0, math.ceil(quantile * ordered.size) - 1)
    return ordered[index].item()


def _money_mean(values: np.ndarray) -> Decimal:
    if values.size == 0:
        raise ValueError("Empirical means require at least one observation.")
    return money(Decimal(str(float(np.mean(values, dtype=np.float64)))))


def _completion_period(
    *,
    step: int | float,
    periods: tuple[date, ...],
    local_date: date,
) -> date:
    resolved = int(step)
    if resolved == 0:
        return local_date
    if not 1 <= resolved <= len(periods):
        raise ValueError("Completion steps must fall inside the simulation horizon.")
    return periods[resolved - 1]


def _robustness_score(
    *,
    all_goals: Decimal,
    deadlines: Decimal,
    reserve: Decimal,
    no_negative: Decimal,
    feasible: Decimal,
) -> Decimal:
    score = Decimal("100") * (
        Decimal("0.30") * all_goals
        + Decimal("0.25") * deadlines
        + Decimal("0.20") * reserve
        + Decimal("0.15") * no_negative
        + Decimal("0.10") * feasible
    )
    return score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _float64(value: bytes, count: int) -> np.ndarray:
    result = np.frombuffer(value, dtype="<f8")
    if result.size != count:
        raise ValueError("Monte Carlo floating sample buffers are inconsistent.")
    return result


def _int16(value: bytes, count: int) -> np.ndarray:
    result = np.frombuffer(value, dtype="<i2")
    if result.size != count:
        raise ValueError("Monte Carlo completion sample buffers are inconsistent.")
    return result


def _boolean(value: bytes, count: int) -> np.ndarray:
    result = np.frombuffer(value, dtype=np.uint8)
    if result.size != count or bool(np.any(result > 1)):
        raise ValueError("Monte Carlo boolean sample buffers are inconsistent.")
    return result.astype(np.bool_)


def _finite(*values: np.ndarray) -> None:
    if any(not bool(np.all(np.isfinite(value))) for value in values):
        raise ValueError("Monte Carlo samples must remain finite.")


def _hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported scenario risk value: {type(value).__name__}")
