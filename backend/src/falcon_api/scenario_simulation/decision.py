"""Cross-scenario comparison, sensitivity, dominance, and decision ranking."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID

from falcon_api.analytics.types import money
from falcon_api.goal_planning.optimizer import LinearProgramSolver
from falcon_api.scenario_simulation.calibration import (
    calibrate_scenario_uncertainty,
)
from falcon_api.scenario_simulation.evaluation import (
    DeterministicScenarioEvaluation,
    evaluate_deterministic_scenarios,
)
from falcon_api.scenario_simulation.monte_carlo import (
    MonteCarloConfig,
    run_scenario_monte_carlo,
)
from falcon_api.scenario_simulation.paths import (
    DeterministicScenarioPath,
    build_deterministic_scenario_paths,
)
from falcon_api.scenario_simulation.risk import (
    ScenarioRiskMetrics,
    reduce_scenario_risk,
)
from falcon_api.scenario_simulation.semantics import (
    SCENARIO_COMPARISON_POLICY_VERSION,
    SCENARIO_DECISION_POLICY_VERSION,
    SCENARIO_SENSITIVITY_POLICY_VERSION,
    ScenarioCalibrationReliability,
    ScenarioCaseKind,
    ScenarioComparisonStatus,
    ScenarioDecisionReasonCode,
    ScenarioRiskStatus,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceSnapshot


_PROBABILITY_QUANTUM = Decimal("0.000001")
_SCORE_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class ScenarioSensitivitySignal:
    """Bounded attribution signal; it is not a causal-effect claim."""

    factor: str
    occurrence_count: int
    direct_capacity_effect: Decimal
    influence_score: Decimal
    method: str = "direct_effect_plus_equal_outcome_attribution"


@dataclass(frozen=True, slots=True)
class ScenarioAlternativeDecision:
    """One alternative compared with the trusted protected reference."""

    comparison_id: str
    snapshot_id: str
    baseline_path_id: str
    path: DeterministicScenarioPath
    evaluation: DeterministicScenarioEvaluation
    risk: ScenarioRiskMetrics
    status: ScenarioComparisonStatus
    expected_capacity_delta: Decimal | None
    completion_probability_delta: Decimal | None
    deadline_probability_delta: Decimal | None
    reserve_probability_delta: Decimal | None
    negative_savings_probability_delta: Decimal | None
    expected_shortfall_delta: Decimal | None
    tail_shortfall_delta: Decimal | None
    robustness_delta: Decimal | None
    weighted_funding_delta: Decimal
    fully_funded_goal_delta: int
    deadline_met_goal_delta: int
    additional_required_contribution: Decimal
    sensitivity_signals: tuple[ScenarioSensitivitySignal, ...]
    decision_score: Decimal
    rank: int
    recommended: bool
    dominated_by_path_id: str | None
    reason_codes: tuple[ScenarioDecisionReasonCode, ...]


@dataclass(frozen=True, slots=True)
class ScenarioDecisionAnalysis:
    """Complete immutable Batch 4 decision evidence for later persistence."""

    analysis_id: str
    snapshot_id: str
    source_plan_id: UUID
    comparison_policy_version: str
    sensitivity_policy_version: str
    decision_policy_version: str
    baseline_path_id: str
    recommended_path_id: str | None
    trial_count: int
    root_seed: int
    alternatives: tuple[ScenarioAlternativeDecision, ...]
    reason_codes: tuple[ScenarioDecisionReasonCode, ...]


def analyze_scenario_decisions(
    snapshot: ScenarioEvidenceSnapshot,
    *,
    config: MonteCarloConfig | None = None,
    solver: LinearProgramSolver | None = None,
) -> ScenarioDecisionAnalysis:
    """Run each approved pure stage once and rank bounded alternatives."""
    resolved_config = config or MonteCarloConfig()
    paths = build_deterministic_scenario_paths(snapshot)
    calibrations = calibrate_scenario_uncertainty(snapshot, paths=paths)
    evaluations = evaluate_deterministic_scenarios(snapshot, solver=solver)
    simulations = run_scenario_monte_carlo(
        snapshot,
        config=resolved_config,
        solver=solver,
        paths=paths,
        calibrations=calibrations,
        evaluations=evaluations,
    )
    risks = reduce_scenario_risk(
        snapshot,
        calibrations=calibrations,
        evaluations=evaluations,
        simulations=simulations,
    )
    baseline_index = _baseline_index(paths)
    baseline_path = paths[baseline_index]
    baseline_evaluation = evaluations[baseline_index]
    baseline_risk = risks[baseline_index]
    drafts = tuple(
        _draft(
            snapshot=snapshot,
            baseline_path=baseline_path,
            baseline_evaluation=baseline_evaluation,
            baseline_risk=baseline_risk,
            path=path,
            evaluation=evaluation,
            risk=risk,
        )
        for path, evaluation, risk in zip(
            paths,
            evaluations,
            risks,
            strict=True,
        )
    )
    scored = _score_and_rank(drafts)
    recommended = next((item for item in scored if item.recommended), None)
    analysis_reasons = (
        ()
        if recommended is not None
        else (ScenarioDecisionReasonCode.NO_SAFE_ALTERNATIVE,)
    )
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "source_plan_id": snapshot.source_plan.run_id,
        "comparison_policy_version": SCENARIO_COMPARISON_POLICY_VERSION,
        "sensitivity_policy_version": SCENARIO_SENSITIVITY_POLICY_VERSION,
        "decision_policy_version": SCENARIO_DECISION_POLICY_VERSION,
        "baseline_path_id": baseline_path.path_id,
        "recommended_path_id": (
            recommended.path.path_id if recommended is not None else None
        ),
        "trial_count": resolved_config.trial_count,
        "root_seed": simulations[0].root_seed,
        "comparisons": tuple(item.comparison_id for item in scored),
        "reasons": analysis_reasons,
    }
    result = ScenarioDecisionAnalysis(
        analysis_id=_hash(payload),
        snapshot_id=snapshot.snapshot_id,
        source_plan_id=snapshot.source_plan.run_id,
        comparison_policy_version=SCENARIO_COMPARISON_POLICY_VERSION,
        sensitivity_policy_version=SCENARIO_SENSITIVITY_POLICY_VERSION,
        decision_policy_version=SCENARIO_DECISION_POLICY_VERSION,
        baseline_path_id=baseline_path.path_id,
        recommended_path_id=(
            recommended.path.path_id if recommended is not None else None
        ),
        trial_count=resolved_config.trial_count,
        root_seed=simulations[0].root_seed,
        alternatives=scored,
        reason_codes=analysis_reasons,
    )
    validate_scenario_decision_analysis(snapshot=snapshot, analysis=result)
    return result


def validate_scenario_decision_analysis(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    analysis: ScenarioDecisionAnalysis,
) -> None:
    """Reject a mutated or cross-snapshot decision graph before storage."""
    if (
        analysis.snapshot_id != snapshot.snapshot_id
        or analysis.source_plan_id != snapshot.source_plan.run_id
        or analysis.comparison_policy_version
        != SCENARIO_COMPARISON_POLICY_VERSION
        or analysis.sensitivity_policy_version
        != SCENARIO_SENSITIVITY_POLICY_VERSION
        or analysis.decision_policy_version != SCENARIO_DECISION_POLICY_VERSION
    ):
        raise ValueError("Scenario decisions must use the trusted snapshot and policies.")
    alternatives = analysis.alternatives
    path_ids = tuple(item.path.path_id for item in alternatives)
    if not alternatives or len(path_ids) != len(set(path_ids)):
        raise ValueError("Scenario decisions require unique alternatives.")
    if analysis.baseline_path_id not in path_ids:
        raise ValueError("Scenario decisions require the protected baseline.")
    if tuple(item.rank for item in alternatives) != tuple(
        range(1, len(alternatives) + 1)
    ):
        raise ValueError("Scenario decision ranks must be contiguous and ordered.")
    recommended = tuple(item for item in alternatives if item.recommended)
    if len(recommended) > 1:
        raise ValueError("Scenario decisions can recommend at most one alternative.")
    if recommended:
        selected = recommended[0]
        if (
            analysis.recommended_path_id != selected.path.path_id
            or selected.rank != 1
            or selected.dominated_by_path_id is not None
        ):
            raise ValueError("Scenario recommendation metadata is inconsistent.")
    elif analysis.recommended_path_id is not None:
        raise ValueError("Scenario recommendation identifiers must be consistent.")
    for item in alternatives:
        if (
            item.snapshot_id != snapshot.snapshot_id
            or item.path.snapshot_id != snapshot.snapshot_id
            or item.evaluation.snapshot_id != snapshot.snapshot_id
            or item.risk.snapshot_id != snapshot.snapshot_id
            or item.path.path_id != item.evaluation.path_id
            or item.path.path_id != item.risk.path_id
            or item.baseline_path_id != analysis.baseline_path_id
            or item.comparison_id != _hash(_comparison_payload(item))
            or not Decimal("0") <= item.decision_score <= Decimal("100")
        ):
            raise ValueError("Scenario comparison evidence is inconsistent.")
    expected_payload = {
        "snapshot_id": analysis.snapshot_id,
        "source_plan_id": analysis.source_plan_id,
        "comparison_policy_version": analysis.comparison_policy_version,
        "sensitivity_policy_version": analysis.sensitivity_policy_version,
        "decision_policy_version": analysis.decision_policy_version,
        "baseline_path_id": analysis.baseline_path_id,
        "recommended_path_id": analysis.recommended_path_id,
        "trial_count": analysis.trial_count,
        "root_seed": analysis.root_seed,
        "comparisons": tuple(item.comparison_id for item in alternatives),
        "reasons": analysis.reason_codes,
    }
    if analysis.analysis_id != _hash(expected_payload):
        raise ValueError("Scenario decision identity is inconsistent.")


def _baseline_index(paths: tuple[DeterministicScenarioPath, ...]) -> int:
    candidates = tuple(
        index
        for index, path in enumerate(paths)
        if path.kind is ScenarioCaseKind.PROTECTED and path.assumptions is None
    )
    if len(candidates) != 1:
        raise ValueError("Scenario comparison requires one protected reference.")
    return candidates[0]


def _draft(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    baseline_path: DeterministicScenarioPath,
    baseline_evaluation: DeterministicScenarioEvaluation,
    baseline_risk: ScenarioRiskMetrics,
    path: DeterministicScenarioPath,
    evaluation: DeterministicScenarioEvaluation,
    risk: ScenarioRiskMetrics,
) -> ScenarioAlternativeDecision:
    status = {
        ScenarioRiskStatus.AVAILABLE: ScenarioComparisonStatus.AVAILABLE,
        ScenarioRiskStatus.LIMITED: ScenarioComparisonStatus.LIMITED,
        ScenarioRiskStatus.BLOCKED: ScenarioComparisonStatus.BLOCKED,
        ScenarioRiskStatus.UNAVAILABLE: ScenarioComparisonStatus.UNAVAILABLE,
    }[risk.status]
    required = _additional_required_contribution(snapshot=snapshot, path=path)
    reasons: list[ScenarioDecisionReasonCode] = []
    if path.path_id == baseline_path.path_id:
        reasons.append(ScenarioDecisionReasonCode.PROTECTED_BASELINE)
    completion_delta = _probability_delta(
        risk.all_goals_completion_probability,
        baseline_risk.all_goals_completion_probability,
    )
    deadline_delta = _probability_delta(
        risk.all_deadlines_met_probability,
        baseline_risk.all_deadlines_met_probability,
    )
    reserve_delta = _probability_delta(
        risk.emergency_reserve_coverage_probability,
        baseline_risk.emergency_reserve_coverage_probability,
    )
    negative_delta = _probability_delta(
        risk.negative_savings_probability,
        baseline_risk.negative_savings_probability,
    )
    expected_shortfall_delta = _money_delta(
        risk.expected_total_shortfall,
        baseline_risk.expected_total_shortfall,
    )
    tail_delta = _money_delta(
        risk.tail_expected_shortfall_90,
        baseline_risk.tail_expected_shortfall_90,
    )
    if completion_delta is not None and completion_delta > 0:
        reasons.append(ScenarioDecisionReasonCode.COMPLETION_IMPROVED)
    if deadline_delta is not None and deadline_delta > 0:
        reasons.append(ScenarioDecisionReasonCode.DEADLINES_IMPROVED)
    if reserve_delta is not None and reserve_delta >= 0:
        reasons.append(ScenarioDecisionReasonCode.RESERVE_PRESERVED)
    if (
        negative_delta is not None
        and negative_delta < 0
        or tail_delta is not None
        and tail_delta < 0
    ):
        reasons.append(ScenarioDecisionReasonCode.DOWNSIDE_REDUCED)
    weighted_delta = (
        evaluation.weighted_funding_score
        - baseline_evaluation.weighted_funding_score
    ).quantize(_PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN)
    if weighted_delta > 0:
        reasons.append(ScenarioDecisionReasonCode.WEIGHTED_FUNDING_IMPROVED)
    if required > 0:
        reasons.append(ScenarioDecisionReasonCode.ADDED_CONTRIBUTION_REQUIRED)
    if status is ScenarioComparisonStatus.LIMITED:
        reasons.append(ScenarioDecisionReasonCode.LIMITED_EVIDENCE)
    result = ScenarioAlternativeDecision(
        comparison_id="",
        snapshot_id=snapshot.snapshot_id,
        baseline_path_id=baseline_path.path_id,
        path=path,
        evaluation=evaluation,
        risk=risk,
        status=status,
        expected_capacity_delta=_money_delta(
            risk.expected_capacity,
            baseline_risk.expected_capacity,
        ),
        completion_probability_delta=completion_delta,
        deadline_probability_delta=deadline_delta,
        reserve_probability_delta=reserve_delta,
        negative_savings_probability_delta=negative_delta,
        expected_shortfall_delta=expected_shortfall_delta,
        tail_shortfall_delta=tail_delta,
        robustness_delta=_score_delta(
            risk.robustness_score,
            baseline_risk.robustness_score,
        ),
        weighted_funding_delta=weighted_delta,
        fully_funded_goal_delta=(
            evaluation.comparison.scenario_fully_funded_goal_count
            - baseline_evaluation.comparison.scenario_fully_funded_goal_count
        ),
        deadline_met_goal_delta=(
            evaluation.comparison.scenario_deadline_met_goal_count
            - baseline_evaluation.comparison.scenario_deadline_met_goal_count
        ),
        additional_required_contribution=required,
        sensitivity_signals=_sensitivity_signals(
            path=path,
            baseline=baseline_path,
        ),
        decision_score=Decimal("0.0000"),
        rank=0,
        recommended=False,
        dominated_by_path_id=None,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
    return result


def _score_and_rank(
    drafts: tuple[ScenarioAlternativeDecision, ...],
) -> tuple[ScenarioAlternativeDecision, ...]:
    available = tuple(item for item in drafts if _eligible(item))
    max_shortfall = _maximum(available, "expected_total_shortfall")
    max_tail = _maximum(available, "tail_expected_shortfall_90")
    max_weighted = max(
        (item.evaluation.weighted_funding_score for item in available),
        default=Decimal("0"),
    )
    max_required = max(
        (item.additional_required_contribution for item in available),
        default=Decimal("0"),
    )
    scored = tuple(
        replace(
            item,
            decision_score=_decision_score(
                item,
                max_shortfall=max_shortfall,
                max_tail=max_tail,
                max_weighted=max_weighted,
                max_required=max_required,
            ),
        )
        for item in drafts
    )
    dominated = tuple(
        replace(item, dominated_by_path_id=_dominator(item, scored))
        for item in scored
    )
    ordered = sorted(
        dominated,
        key=lambda item: (
            not _eligible(item),
            item.dominated_by_path_id is not None,
            -item.decision_score,
            -(item.risk.robustness_score or Decimal("0")),
            _case_preference(item.path.kind),
            item.path.path_id,
        ),
    )
    recommendation = next(
        (
            item.path.path_id
            for item in ordered
            if _eligible(item) and item.dominated_by_path_id is None
        ),
        None,
    )
    result: list[ScenarioAlternativeDecision] = []
    for rank, item in enumerate(ordered, start=1):
        reasons = list(item.reason_codes)
        if item.dominated_by_path_id is not None:
            reasons.append(ScenarioDecisionReasonCode.DOMINATED_ALTERNATIVE)
        recommended = item.path.path_id == recommendation
        if recommended:
            reasons.append(ScenarioDecisionReasonCode.RECOMMENDED_ALTERNATIVE)
        resolved = replace(
            item,
            rank=rank,
            recommended=recommended,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )
        resolved = replace(
            resolved,
            comparison_id=_hash(_comparison_payload(resolved)),
        )
        result.append(resolved)
    return tuple(result)


def _decision_score(
    item: ScenarioAlternativeDecision,
    *,
    max_shortfall: Decimal,
    max_tail: Decimal,
    max_weighted: Decimal,
    max_required: Decimal,
) -> Decimal:
    if not _eligible(item):
        return Decimal("0.0000")
    risk = item.risk
    components = (
        (Decimal("0.15"), risk.all_goals_completion_probability),
        (Decimal("0.15"), risk.all_deadlines_met_probability),
        (Decimal("0.15"), risk.emergency_reserve_coverage_probability),
        (
            Decimal("0.10"),
            Decimal("1") - risk.negative_savings_probability,
        ),
        (Decimal("0.10"), risk.constraint_feasibility_probability),
        (
            Decimal("0.10"),
            _lower_is_better(risk.expected_total_shortfall, max_shortfall),
        ),
        (
            Decimal("0.10"),
            _lower_is_better(risk.tail_expected_shortfall_90, max_tail),
        ),
        (
            Decimal("0.05"),
            _higher_is_better(item.evaluation.weighted_funding_score, max_weighted),
        ),
        (
            Decimal("0.05"),
            _lower_is_better(item.additional_required_contribution, max_required),
        ),
        (Decimal("0.05"), _reliability_score(risk.reliability)),
    )
    if any(value is None for _, value in components):
        return Decimal("0.0000")
    score = Decimal("100") * sum(
        weight * value for weight, value in components if value is not None
    )
    return score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _dominator(
    candidate: ScenarioAlternativeDecision,
    alternatives: tuple[ScenarioAlternativeDecision, ...],
) -> str | None:
    if not _eligible(candidate):
        return None
    dominators = tuple(
        item
        for item in alternatives
        if item.path.path_id != candidate.path.path_id
        and _eligible(item)
        and _dominates(item, candidate)
    )
    if not dominators:
        return None
    return min(
        dominators,
        key=lambda item: (-item.decision_score, item.path.path_id),
    ).path.path_id


def _dominates(
    left: ScenarioAlternativeDecision,
    right: ScenarioAlternativeDecision,
) -> bool:
    left_risk = left.risk
    right_risk = right.risk
    higher = (
        (
            left_risk.all_goals_completion_probability,
            right_risk.all_goals_completion_probability,
        ),
        (
            left_risk.all_deadlines_met_probability,
            right_risk.all_deadlines_met_probability,
        ),
        (
            left_risk.emergency_reserve_coverage_probability,
            right_risk.emergency_reserve_coverage_probability,
        ),
        (
            left_risk.constraint_feasibility_probability,
            right_risk.constraint_feasibility_probability,
        ),
        (
            left.evaluation.weighted_funding_score,
            right.evaluation.weighted_funding_score,
        ),
        (
            Decimal(_reliability_rank(left_risk.reliability)),
            Decimal(_reliability_rank(right_risk.reliability)),
        ),
    )
    lower = (
        (
            left_risk.negative_savings_probability,
            right_risk.negative_savings_probability,
        ),
        (
            left_risk.expected_total_shortfall,
            right_risk.expected_total_shortfall,
        ),
        (
            left_risk.tail_expected_shortfall_90,
            right_risk.tail_expected_shortfall_90,
        ),
        (
            left.additional_required_contribution,
            right.additional_required_contribution,
        ),
    )
    values = (*higher, *lower)
    if any(left_value is None or right_value is None for left_value, right_value in values):
        return False
    no_worse = all(left_value >= right_value for left_value, right_value in higher)
    no_worse &= all(left_value <= right_value for left_value, right_value in lower)
    strictly_better = any(
        left_value > right_value for left_value, right_value in higher
    ) or any(left_value < right_value for left_value, right_value in lower)
    return no_worse and strictly_better


def _sensitivity_signals(
    *,
    path: DeterministicScenarioPath,
    baseline: DeterministicScenarioPath,
) -> tuple[ScenarioSensitivitySignal, ...]:
    assumptions = path.assumptions
    if assumptions is None:
        effects = [("reference_band", 1, money(path.selected_total - baseline.selected_total))]
    else:
        effects: list[tuple[str, int, Decimal]] = []
        if assumptions.income_change_percent or assumptions.income_interruptions:
            effects.append(
                (
                    "income",
                    int(bool(assumptions.income_change_percent))
                    + len(assumptions.income_interruptions),
                    money(sum((item.income_delta for item in path.periods), Decimal("0"))),
                )
            )
        if assumptions.expense_change_percent:
            effects.append(
                (
                    "expense",
                    1,
                    money(-sum((item.expense_delta for item in path.periods), Decimal("0"))),
                )
            )
        if assumptions.one_time_expenses:
            effects.append(
                (
                    "one_time_expense",
                    len(assumptions.one_time_expenses),
                    money(-sum((item.one_time_expense for item in path.periods), Decimal("0"))),
                )
            )
        if assumptions.recurring_expense_adjustments:
            effects.append(
                (
                    "recurring_expense",
                    len(assumptions.recurring_expense_adjustments),
                    money(
                        -sum(
                            (item.recurring_expense_delta for item in path.periods),
                            Decimal("0"),
                        )
                    ),
                )
            )
        if assumptions.debt_payment_adjustments:
            effects.append(
                (
                    "debt_payment",
                    len(assumptions.debt_payment_adjustments),
                    money(
                        -sum(
                            (item.debt_payment_delta for item in path.periods),
                            Decimal("0"),
                        )
                    ),
                )
            )
        if assumptions.goal_adjustments:
            effects.append(("goal_terms", len(assumptions.goal_adjustments), Decimal("0.0000")))
        if assumptions.emergency_fund_target_months is not None:
            effects.append(
                (
                    "emergency_reserve",
                    1,
                    money(baseline.emergency_reserve_amount - path.emergency_reserve_amount),
                )
            )
    if not effects:
        raise ValueError("Scenario sensitivity requires at least one factor.")
    direct_total = sum((abs(item[2]) for item in effects), Decimal("0"))
    count = Decimal(len(effects))
    result = tuple(
        ScenarioSensitivitySignal(
            factor=factor,
            occurrence_count=occurrences,
            direct_capacity_effect=money(effect),
            influence_score=(
                Decimal("40") / count
                + (
                    Decimal("60") * abs(effect) / direct_total
                    if direct_total > 0
                    else Decimal("60") / count
                )
            ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN),
        )
        for factor, occurrences, effect in effects
    )
    return result


def _additional_required_contribution(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
) -> Decimal:
    assumptions = path.assumptions
    if assumptions is None:
        return Decimal("0.0000")
    goals = {item.goal_id: item for item in snapshot.goals}
    total = Decimal("0")
    for adjustment in assumptions.goal_adjustments:
        delta = adjustment.monthly_contribution_delta
        if delta is None or delta <= 0:
            continue
        target = adjustment.target_date or goals[adjustment.goal_id].target_date
        months = sum(
            period.period_start <= target
            and not (
                adjustment.pause_start is not None
                and adjustment.pause_end is not None
                and adjustment.pause_start
                <= period.period_start
                <= adjustment.pause_end
            )
            for period in snapshot.periods
        )
        total += delta * months
    return money(total)


def _comparison_payload(item: ScenarioAlternativeDecision) -> dict[str, Any]:
    return {
        "snapshot_id": item.snapshot_id,
        "baseline_path_id": item.baseline_path_id,
        "path_id": item.path.path_id,
        "evaluation_id": item.evaluation.evaluation_id,
        "risk_id": item.risk.risk_id,
        "status": item.status,
        "expected_capacity_delta": item.expected_capacity_delta,
        "completion_probability_delta": item.completion_probability_delta,
        "deadline_probability_delta": item.deadline_probability_delta,
        "reserve_probability_delta": item.reserve_probability_delta,
        "negative_savings_probability_delta": item.negative_savings_probability_delta,
        "expected_shortfall_delta": item.expected_shortfall_delta,
        "tail_shortfall_delta": item.tail_shortfall_delta,
        "robustness_delta": item.robustness_delta,
        "weighted_funding_delta": item.weighted_funding_delta,
        "fully_funded_goal_delta": item.fully_funded_goal_delta,
        "deadline_met_goal_delta": item.deadline_met_goal_delta,
        "additional_required_contribution": item.additional_required_contribution,
        "sensitivity_signals": item.sensitivity_signals,
        "decision_score": item.decision_score,
        "rank": item.rank,
        "recommended": item.recommended,
        "dominated_by_path_id": item.dominated_by_path_id,
        "reason_codes": item.reason_codes,
    }


def _eligible(item: ScenarioAlternativeDecision) -> bool:
    return item.status in {
        ScenarioComparisonStatus.AVAILABLE,
        ScenarioComparisonStatus.LIMITED,
    }


def _maximum(
    alternatives: tuple[ScenarioAlternativeDecision, ...],
    field: str,
) -> Decimal:
    values = tuple(
        getattr(item.risk, field)
        for item in alternatives
        if getattr(item.risk, field) is not None
    )
    return max(values, default=Decimal("0"))


def _lower_is_better(value: Decimal | None, maximum: Decimal) -> Decimal | None:
    if value is None:
        return None
    if maximum <= 0:
        return Decimal("1")
    return max(Decimal("0"), Decimal("1") - value / maximum)


def _higher_is_better(value: Decimal, maximum: Decimal) -> Decimal:
    return Decimal("1") if maximum <= 0 else max(Decimal("0"), value / maximum)


def _reliability_score(value: ScenarioCalibrationReliability) -> Decimal:
    return {
        ScenarioCalibrationReliability.NORMAL: Decimal("1"),
        ScenarioCalibrationReliability.PROVISIONAL: Decimal("0.75"),
        ScenarioCalibrationReliability.CONSERVATIVE: Decimal("0.50"),
        ScenarioCalibrationReliability.UNAVAILABLE: Decimal("0"),
    }[value]


def _reliability_rank(value: ScenarioCalibrationReliability) -> int:
    return {
        ScenarioCalibrationReliability.NORMAL: 3,
        ScenarioCalibrationReliability.PROVISIONAL: 2,
        ScenarioCalibrationReliability.CONSERVATIVE: 1,
        ScenarioCalibrationReliability.UNAVAILABLE: 0,
    }[value]


def _case_preference(value: ScenarioCaseKind) -> int:
    """Prefer the conservative reference when decision evidence is identical."""
    return {
        ScenarioCaseKind.PROTECTED: 0,
        ScenarioCaseKind.EXPECTED: 1,
        ScenarioCaseKind.USER_DEFINED: 2,
        ScenarioCaseKind.UPSIDE: 3,
    }[value]


def _probability_delta(
    value: Decimal | None,
    baseline: Decimal | None,
) -> Decimal | None:
    if value is None or baseline is None:
        return None
    return (value - baseline).quantize(
        _PROBABILITY_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _money_delta(
    value: Decimal | None,
    baseline: Decimal | None,
) -> Decimal | None:
    return None if value is None or baseline is None else money(value - baseline)


def _score_delta(
    value: Decimal | None,
    baseline: Decimal | None,
) -> Decimal | None:
    if value is None or baseline is None:
        return None
    return (value - baseline).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


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
    raise TypeError(f"Unsupported scenario decision value: {type(value).__name__}")
