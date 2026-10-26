"""Bounded seeded Monte Carlo replay for Phase 11 scenario paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

import numpy as np

from falcon_api.goal_planning.optimizer import LinearProgramSolver
from falcon_api.models.enums import GoalType
from falcon_api.scenario_simulation.calibration import (
    ScenarioUncertaintyCalibration,
    calibrate_scenario_uncertainty,
)
from falcon_api.scenario_simulation.evaluation import (
    DeterministicScenarioEvaluation,
    build_scenario_allocation_bounds,
    build_scenario_planning_snapshot,
    evaluate_deterministic_scenarios,
)
from falcon_api.scenario_simulation.paths import (
    DeterministicScenarioPath,
    build_deterministic_scenario_paths,
)
from falcon_api.scenario_simulation.semantics import (
    DEFAULT_MONTE_CARLO_TRIALS,
    MAX_MONTE_CARLO_SEED,
    MAX_MONTE_CARLO_TRIALS,
    MAX_MONTE_CARLO_WORK_UNITS,
    MAX_SCENARIO_HORIZON_MONTHS,
    SCENARIO_MONTE_CARLO_POLICY_VERSION,
    SCENARIO_UNCERTAINTY_POLICY_VERSION,
    ScenarioCalibrationStatus,
    ScenarioEvaluationStatus,
    ScenarioMonteCarloStatus,
    ScenarioReasonCode,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceSnapshot


MONTE_CARLO_PROBABILITY_METHOD = "seeded_empirical_monte_carlo"
MONTE_CARLO_ALLOCATION_METHOD = "phase_10_ranked_guarded_replay"
MONTE_CARLO_SAMPLE_ENCODING = "little_endian_float64_int16_uint8"
_QUANTILE_PROBABILITIES = np.array(
    [0.0, 0.025, 0.10, 0.50, 0.90, 0.975, 1.0],
    dtype=np.float64,
)
_EPSILON = 1e-7


@dataclass(frozen=True, slots=True)
class MonteCarloConfig:
    """Bound trial count and optionally pin a replay seed."""

    trial_count: int = DEFAULT_MONTE_CARLO_TRIALS
    seed: int | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.trial_count, bool)
            or not isinstance(self.trial_count, int)
            or not 1 <= self.trial_count <= MAX_MONTE_CARLO_TRIALS
        ):
            raise ValueError(
                f"Monte Carlo trials must be between 1 and {MAX_MONTE_CARLO_TRIALS}."
            )
        if self.seed is not None and (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed <= MAX_MONTE_CARLO_SEED
        ):
            raise ValueError("Monte Carlo seeds must be bounded non-negative integers.")


@dataclass(frozen=True, slots=True)
class ScenarioGoalTrialSamples:
    """Compact immutable samples consumed only by the Phase 11 risk reducer."""

    goal_id: UUID
    rank: int
    completion_steps: bytes
    final_shortfalls: bytes
    deadline_met: bytes


@dataclass(frozen=True, slots=True)
class ScenarioMonteCarloSimulation:
    """One reproducible stochastic replay with compact bounded sample buffers."""

    simulation_id: str
    snapshot_id: str
    path_id: str
    calibration_id: str
    policy_version: str
    status: ScenarioMonteCarloStatus
    root_seed: int
    scenario_seed: int
    trial_count: int
    horizon_months: int
    probability_method: str
    allocation_method: str
    sample_encoding: str
    sample_digest: str
    capacity_totals: bytes
    total_shortfalls: bytes
    negative_savings: bytes
    reserve_covered: bytes
    constraint_feasible: bytes
    all_goals_completed: bytes
    all_deadlines_met: bytes
    goal_samples: tuple[ScenarioGoalTrialSamples, ...]
    reason_codes: tuple[ScenarioReasonCode, ...]


def run_scenario_monte_carlo(
    snapshot: ScenarioEvidenceSnapshot,
    *,
    config: MonteCarloConfig | None = None,
    solver: LinearProgramSolver | None = None,
    paths: tuple[DeterministicScenarioPath, ...] | None = None,
    calibrations: tuple[ScenarioUncertaintyCalibration, ...] | None = None,
    evaluations: tuple[DeterministicScenarioEvaluation, ...] | None = None,
) -> tuple[ScenarioMonteCarloSimulation, ...]:
    """Run bounded paths with reproducible common random draws and no persistence."""
    resolved_config = config or MonteCarloConfig()
    resolved_paths = paths or build_deterministic_scenario_paths(snapshot)
    resolved_calibrations = calibrations or calibrate_scenario_uncertainty(
        snapshot,
        paths=resolved_paths,
    )
    resolved_evaluations = evaluations or evaluate_deterministic_scenarios(
        snapshot,
        solver=solver,
    )
    _validate_inputs(
        snapshot=snapshot,
        paths=resolved_paths,
        calibrations=resolved_calibrations,
        evaluations=resolved_evaluations,
    )
    work_units = resolved_config.trial_count * sum(
        len(calibration.points) * max(1, len(snapshot.goals))
        for calibration, evaluation in zip(
            resolved_calibrations,
            resolved_evaluations,
            strict=True,
        )
        if calibration.status is not ScenarioCalibrationStatus.UNAVAILABLE
        and evaluation.status
        not in {
            ScenarioEvaluationStatus.BLOCKED,
            ScenarioEvaluationStatus.INFEASIBLE,
            ScenarioEvaluationStatus.UNAVAILABLE,
        }
    )
    if work_units > MAX_MONTE_CARLO_WORK_UNITS:
        raise ValueError("Monte Carlo request exceeds the bounded work budget.")
    root_seed = (
        resolved_config.seed
        if resolved_config.seed is not None
        else _derived_seed(snapshot.snapshot_id, SCENARIO_MONTE_CARLO_POLICY_VERSION)
    )
    return tuple(
        _simulate_path(
            snapshot=snapshot,
            path=path,
            calibration=calibration,
            evaluation=evaluation,
            trial_count=resolved_config.trial_count,
            root_seed=root_seed,
        )
        for path, calibration, evaluation in zip(
            resolved_paths,
            resolved_calibrations,
            resolved_evaluations,
            strict=True,
        )
    )


def _validate_inputs(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    paths: tuple[DeterministicScenarioPath, ...],
    calibrations: tuple[ScenarioUncertaintyCalibration, ...],
    evaluations: tuple[DeterministicScenarioEvaluation, ...],
) -> None:
    if not (len(paths) == len(calibrations) == len(evaluations)):
        raise ValueError("Monte Carlo inputs must contain the same scenario paths.")
    if len({path.path_id for path in paths}) != len(paths):
        raise ValueError("Monte Carlo scenario paths must be unique.")
    for path, calibration, evaluation in zip(
        paths,
        calibrations,
        evaluations,
        strict=True,
    ):
        if (
            path.snapshot_id != snapshot.snapshot_id
            or calibration.snapshot_id != snapshot.snapshot_id
            or evaluation.snapshot_id != snapshot.snapshot_id
            or calibration.path_id != path.path_id
            or evaluation.path_id != path.path_id
        ):
            raise ValueError(
                "Monte Carlo inputs must share one snapshot and path order."
            )
        expected_periods = tuple(item.period_start for item in path.periods)
        calibration_periods = tuple(
            item.period_start for item in calibration.points
        )
        if calibration.policy_version != SCENARIO_UNCERTAINTY_POLICY_VERSION:
            raise ValueError("Monte Carlo calibration policies must be supported.")
        if calibration.status is ScenarioCalibrationStatus.UNAVAILABLE:
            if calibration.points:
                raise ValueError("Unavailable calibrations cannot contain samples.")
        elif (
            not calibration.points
            or calibration_periods != expected_periods
            or len(calibration.points) > MAX_SCENARIO_HORIZON_MONTHS
        ):
            raise ValueError("Monte Carlo calibration periods must match the path.")
        for point in calibration.points:
            values = (
                point.raw_lower_95,
                point.raw_lower_80,
                point.raw_expected,
                point.raw_upper_80,
                point.raw_upper_95,
            )
            if (
                any(not value.is_finite() for value in values)
                or values != tuple(sorted(values))
            ):
                raise ValueError(
                    "Monte Carlo calibration knots must be finite and ordered."
                )
        if (
            evaluation.status
            not in {
                ScenarioEvaluationStatus.BLOCKED,
                ScenarioEvaluationStatus.INFEASIBLE,
                ScenarioEvaluationStatus.UNAVAILABLE,
            }
            and evaluation.ranking is None
        ):
            raise ValueError("Monte Carlo evaluation rankings are required.")


def _simulate_path(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
    calibration: ScenarioUncertaintyCalibration,
    evaluation: DeterministicScenarioEvaluation,
    trial_count: int,
    root_seed: int,
) -> ScenarioMonteCarloSimulation:
    scenario_seed = _derived_seed(str(root_seed), "common_random_numbers_v1")
    if calibration.status is ScenarioCalibrationStatus.UNAVAILABLE:
        return _empty_simulation(
            snapshot=snapshot,
            path=path,
            calibration=calibration,
            status=ScenarioMonteCarloStatus.UNAVAILABLE,
            root_seed=root_seed,
            scenario_seed=scenario_seed,
            reasons=calibration.reason_codes,
        )
    if evaluation.status in {
        ScenarioEvaluationStatus.BLOCKED,
        ScenarioEvaluationStatus.INFEASIBLE,
        ScenarioEvaluationStatus.UNAVAILABLE,
    }:
        status = (
            ScenarioMonteCarloStatus.UNAVAILABLE
            if evaluation.status is ScenarioEvaluationStatus.UNAVAILABLE
            else ScenarioMonteCarloStatus.BLOCKED
        )
        return _empty_simulation(
            snapshot=snapshot,
            path=path,
            calibration=calibration,
            status=status,
            root_seed=root_seed,
            scenario_seed=scenario_seed,
            reasons=(*calibration.reason_codes, *evaluation.reason_codes),
        )

    planning = build_scenario_planning_snapshot(snapshot=snapshot, path=path)
    bounds = build_scenario_allocation_bounds(
        evidence=snapshot,
        path=path,
        planning=planning,
    )
    assert evaluation.ranking is not None
    raw_capacity = _sample_capacity(
        calibration=calibration,
        trial_count=trial_count,
        scenario_seed=scenario_seed,
    )
    sampled = _replay_allocations(
        planning=planning,
        ranking=evaluation.ranking,
        raw_capacity=raw_capacity,
        reserve=float(path.emergency_reserve_amount),
        bounds=bounds,
    )
    buffers = _sample_buffers(sampled)
    digest = _sample_digest(buffers)
    reasons = [
        *calibration.reason_codes,
        ScenarioReasonCode.SEEDED_MONTE_CARLO_COMPLETED,
    ]
    if not bool(np.all(sampled["constraint_feasible"])):
        reasons.append(ScenarioReasonCode.MONTE_CARLO_CONSTRAINT_INFEASIBLE)
    status = (
        ScenarioMonteCarloStatus.CONSERVATIVE_FALLBACK
        if calibration.status is ScenarioCalibrationStatus.CONSERVATIVE_FALLBACK
        else ScenarioMonteCarloStatus.COMPLETED
    )
    goal_samples = tuple(
        ScenarioGoalTrialSamples(
            goal_id=item.goal_id,
            rank=item.rank,
            completion_steps=_pack_int16(sampled["completion_steps"][:, index]),
            final_shortfalls=_pack_float64(sampled["remaining"][:, index]),
            deadline_met=_pack_bool(sampled["deadline_met"][:, index]),
        )
        for index, item in enumerate(evaluation.ranking.items)
    )
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "path_id": path.path_id,
        "calibration_id": calibration.calibration_id,
        "policy_version": SCENARIO_MONTE_CARLO_POLICY_VERSION,
        "status": status,
        "root_seed": root_seed,
        "scenario_seed": scenario_seed,
        "trial_count": trial_count,
        "sample_digest": digest,
    }
    return ScenarioMonteCarloSimulation(
        simulation_id=_json_hash(payload),
        snapshot_id=snapshot.snapshot_id,
        path_id=path.path_id,
        calibration_id=calibration.calibration_id,
        policy_version=SCENARIO_MONTE_CARLO_POLICY_VERSION,
        status=status,
        root_seed=root_seed,
        scenario_seed=scenario_seed,
        trial_count=trial_count,
        horizon_months=len(calibration.points),
        probability_method=MONTE_CARLO_PROBABILITY_METHOD,
        allocation_method=MONTE_CARLO_ALLOCATION_METHOD,
        sample_encoding=MONTE_CARLO_SAMPLE_ENCODING,
        sample_digest=digest,
        capacity_totals=buffers["capacity_totals"],
        total_shortfalls=buffers["total_shortfalls"],
        negative_savings=buffers["negative_savings"],
        reserve_covered=buffers["reserve_covered"],
        constraint_feasible=buffers["constraint_feasible"],
        all_goals_completed=buffers["all_goals_completed"],
        all_deadlines_met=buffers["all_deadlines_met"],
        goal_samples=goal_samples,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _sample_capacity(
    *,
    calibration: ScenarioUncertaintyCalibration,
    trial_count: int,
    scenario_seed: int,
) -> np.ndarray:
    generator = np.random.Generator(np.random.PCG64(scenario_seed))
    uniforms = generator.random((trial_count, len(calibration.points)))
    result = np.empty_like(uniforms, dtype=np.float64)
    for index, point in enumerate(calibration.points):
        knots = np.array(
            [
                float(point.raw_lower_95),
                float(point.raw_lower_95),
                float(point.raw_lower_80),
                float(point.raw_expected),
                float(point.raw_upper_80),
                float(point.raw_upper_95),
                float(point.raw_upper_95),
            ],
            dtype=np.float64,
        )
        result[:, index] = np.interp(
            uniforms[:, index],
            _QUANTILE_PROBABILITIES,
            knots,
        )
    if not bool(np.all(np.isfinite(result))):
        raise ValueError("Monte Carlo sampling produced a non-finite capacity.")
    return result


def _replay_allocations(
    *,
    planning: Any,
    ranking: Any,
    raw_capacity: np.ndarray,
    reserve: float,
    bounds: tuple[Any, ...],
) -> dict[str, np.ndarray]:
    trials, horizon = raw_capacity.shape
    capacity = np.maximum(raw_capacity, 0.0)
    goals = {item.goal_id: item for item in planning.goals}
    ordered_goals = tuple(goals[item.goal_id] for item in ranking.items)
    goal_count = len(ordered_goals)
    initial_remaining = np.array(
        [float(item.remaining_amount) for item in ordered_goals],
        dtype=np.float64,
    )
    remaining = np.broadcast_to(
        initial_remaining,
        (trials, goal_count),
    ).copy()
    completion_steps = np.full((trials, goal_count), -1, dtype=np.int16)
    initially_funded = remaining[0] <= _EPSILON
    completion_steps[:, initially_funded] = 0
    feasible = np.ones(trials, dtype=np.bool_)
    cumulative_capacity = np.zeros(trials, dtype=np.float64)
    cumulative_non_emergency = np.zeros(trials, dtype=np.float64)
    bound_map = {
        (item.goal_id, item.period_start): item
        for item in bounds
    }
    periods = tuple(item.period_start for item in planning.savings_capacity.points)
    for period_index, period_start in enumerate(periods):
        available = capacity[:, period_index].copy()
        cumulative_capacity += available
        period_allocated = np.zeros((trials, goal_count), dtype=np.float64)
        for goal_index, ranked in enumerate(ranking.items):
            bound = bound_map.get((ranked.goal_id, period_start))
            minimum = float(bound.minimum_amount) if bound is not None else 0.0
            if minimum <= 0:
                continue
            goal = ordered_goals[goal_index]
            allowed = (
                feasible
                & (available + _EPSILON >= minimum)
                & (remaining[:, goal_index] + _EPSILON >= minimum)
            )
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                reserve_room = (
                    np.maximum(0.0, cumulative_capacity - reserve)
                    - cumulative_non_emergency
                )
                allowed &= reserve_room + _EPSILON >= minimum
            feasible &= allowed
            amount = np.where(allowed, minimum, 0.0)
            period_allocated[:, goal_index] += amount
            available -= amount
            remaining[:, goal_index] -= amount
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                cumulative_non_emergency += amount

        for goal_index, ranked in enumerate(ranking.items):
            goal = ordered_goals[goal_index]
            if (
                not ranked.eligible_for_allocation
                or period_start > goal.target_date
            ):
                continue
            bound = bound_map.get((ranked.goal_id, period_start))
            maximum = (
                float(bound.maximum_amount)
                if bound is not None and bound.maximum_amount is not None
                else np.inf
            )
            room = np.maximum(0.0, maximum - period_allocated[:, goal_index])
            room = np.minimum(room, remaining[:, goal_index])
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                reserve_room = np.maximum(
                    0.0,
                    np.maximum(0.0, cumulative_capacity - reserve)
                    - cumulative_non_emergency,
                )
                room = np.minimum(room, reserve_room)
            amount = np.minimum(available, room)
            amount = np.where(
                feasible
                & (available > _EPSILON)
                & (remaining[:, goal_index] > _EPSILON),
                np.maximum(0.0, amount),
                0.0,
            )
            period_allocated[:, goal_index] += amount
            available -= amount
            remaining[:, goal_index] -= amount
            if goal.goal_type is not GoalType.EMERGENCY_FUND:
                cumulative_non_emergency += amount

        remaining = np.maximum(remaining, 0.0)
        newly_funded = (
            feasible[:, None]
            & (completion_steps < 0)
            & (remaining <= _EPSILON)
        )
        completion_steps[newly_funded] = period_index + 1

    completion_steps[~feasible, :] = -1
    remaining[~feasible, :] = initial_remaining
    deadline_met = np.zeros((trials, goal_count), dtype=np.bool_)
    for goal_index, goal in enumerate(ordered_goals):
        deadline_step = sum(period <= goal.target_date for period in periods)
        completed = completion_steps[:, goal_index]
        deadline_met[:, goal_index] = (
            feasible
            & (completed >= 0)
            & (completed <= deadline_step)
        )
    remaining = np.maximum(remaining, 0.0)
    total_shortfalls = np.sum(remaining, axis=1)
    all_completed = feasible & np.all(remaining <= _EPSILON, axis=1)
    all_deadlines = feasible & np.all(deadline_met, axis=1)
    capacity_totals = np.sum(capacity, axis=1)
    result = {
        "capacity_totals": capacity_totals,
        "total_shortfalls": total_shortfalls,
        "negative_savings": np.any(raw_capacity < 0.0, axis=1),
        "reserve_covered": capacity_totals + _EPSILON >= reserve,
        "constraint_feasible": feasible,
        "all_goals_completed": all_completed,
        "all_deadlines_met": all_deadlines,
        "remaining": remaining,
        "completion_steps": completion_steps,
        "deadline_met": deadline_met,
    }
    if any(not bool(np.all(np.isfinite(value))) for value in result.values()):
        raise ValueError("Monte Carlo replay produced a non-finite result.")
    return result


def _sample_buffers(sampled: dict[str, np.ndarray]) -> dict[str, bytes]:
    return {
        "capacity_totals": _pack_float64(sampled["capacity_totals"]),
        "total_shortfalls": _pack_float64(sampled["total_shortfalls"]),
        "negative_savings": _pack_bool(sampled["negative_savings"]),
        "reserve_covered": _pack_bool(sampled["reserve_covered"]),
        "constraint_feasible": _pack_bool(sampled["constraint_feasible"]),
        "all_goals_completed": _pack_bool(sampled["all_goals_completed"]),
        "all_deadlines_met": _pack_bool(sampled["all_deadlines_met"]),
        "remaining": _pack_float64(sampled["remaining"]),
        "completion_steps": _pack_int16(sampled["completion_steps"]),
        "deadline_met": _pack_bool(sampled["deadline_met"]),
    }


def _sample_digest(buffers: dict[str, bytes]) -> str:
    digest = sha256()
    for name in sorted(buffers):
        digest.update(name.encode("ascii"))
        digest.update(buffers[name])
    return digest.hexdigest()


def _empty_simulation(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
    calibration: ScenarioUncertaintyCalibration,
    status: ScenarioMonteCarloStatus,
    root_seed: int,
    scenario_seed: int,
    reasons: tuple[ScenarioReasonCode, ...],
) -> ScenarioMonteCarloSimulation:
    deduplicated = tuple(dict.fromkeys(reasons))
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "path_id": path.path_id,
        "calibration_id": calibration.calibration_id,
        "policy_version": SCENARIO_MONTE_CARLO_POLICY_VERSION,
        "status": status,
        "root_seed": root_seed,
        "scenario_seed": scenario_seed,
    }
    return ScenarioMonteCarloSimulation(
        simulation_id=_json_hash(payload),
        snapshot_id=snapshot.snapshot_id,
        path_id=path.path_id,
        calibration_id=calibration.calibration_id,
        policy_version=SCENARIO_MONTE_CARLO_POLICY_VERSION,
        status=status,
        root_seed=root_seed,
        scenario_seed=scenario_seed,
        trial_count=0,
        horizon_months=0,
        probability_method=MONTE_CARLO_PROBABILITY_METHOD,
        allocation_method=MONTE_CARLO_ALLOCATION_METHOD,
        sample_encoding=MONTE_CARLO_SAMPLE_ENCODING,
        sample_digest=sha256(b"").hexdigest(),
        capacity_totals=b"",
        total_shortfalls=b"",
        negative_savings=b"",
        reserve_covered=b"",
        constraint_feasible=b"",
        all_goals_completed=b"",
        all_deadlines_met=b"",
        goal_samples=(),
        reason_codes=deduplicated,
    )


def _pack_float64(value: np.ndarray) -> bytes:
    return np.asarray(value, dtype="<f8").tobytes()


def _pack_int16(value: np.ndarray) -> bytes:
    return np.asarray(value, dtype="<i2").tobytes()


def _pack_bool(value: np.ndarray) -> bytes:
    return np.asarray(value, dtype=np.uint8).tobytes()


def _derived_seed(*values: str) -> int:
    encoded = "\x1f".join(values).encode("utf-8")
    return int.from_bytes(sha256(encoded).digest()[:8], "big") & MAX_MONTE_CARLO_SEED


def _json_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
