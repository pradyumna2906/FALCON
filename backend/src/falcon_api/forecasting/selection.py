"""Deterministic candidate ranking and one-time final-test evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from falcon_api.forecasting.candidates import (
    ForecastCandidateError,
    ForecastCandidateFitError,
    ForecastCandidateUnavailableError,
)
from falcon_api.forecasting.evaluation import (
    EVALUATION_QUANTUM,
    CandidateEvaluation,
    ChronologicalEvaluationPlan,
    ForecastCandidate,
    ForecastErrorMetrics,
    calculate_forecast_error_metrics,
    evaluate_candidate,
)


FORECAST_SELECTION_POLICY_VERSION = "2026.1"
DEFAULT_COMPLEX_MODEL_IMPROVEMENT = Decimal("0.050000")
_BASELINE_CODES = frozenset(
    {
        "last_value",
        "historical_mean",
        "historical_median",
        "moving_average",
        "seasonal_naive",
        "drift",
    }
)


class SelectionMetric(StrEnum):
    WAPE = "wape"
    MAE = "mae"


class CandidateFailureReason(StrEnum):
    INSUFFICIENT_HISTORY = "insufficient_history"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    FIT_FAILED = "fit_failed"
    EVALUATION_FAILED = "evaluation_failed"


@dataclass(frozen=True, slots=True)
class CandidateFailure:
    model_code: str
    reason: CandidateFailureReason


@dataclass(frozen=True, slots=True)
class FinalTestEvaluation:
    """The selected model's only evaluation against reserved test observations."""

    actual: tuple[Decimal, ...]
    predicted: tuple[Decimal, ...]
    metrics: ForecastErrorMetrics


@dataclass(frozen=True, slots=True)
class ForecastModelSelection:
    """Auditable validation ranking, baseline guardrail, and final test result."""

    policy_version: str
    ranking_metric: SelectionMetric
    minimum_complex_improvement: Decimal
    selected_model_code: str
    selected_is_baseline: bool
    best_baseline_model_code: str | None
    complex_improvement_over_baseline: Decimal | None
    candidate_evaluations: tuple[CandidateEvaluation, ...]
    candidate_failures: tuple[CandidateFailure, ...]
    final_test: FinalTestEvaluation


def select_forecast_model(
    *,
    values: tuple[Decimal, ...],
    plan: ChronologicalEvaluationPlan,
    candidates: tuple[ForecastCandidate, ...],
    minimum_complex_improvement: Decimal = DEFAULT_COMPLEX_MODEL_IMPROVEMENT,
) -> ForecastModelSelection:
    """Rank on validation only, then evaluate the winner once on reserved test data."""
    if not candidates:
        raise ValueError("Model selection requires at least one candidate.")
    codes = tuple(candidate.code for candidate in candidates)
    if any(not code.strip() for code in codes) or len(codes) != len(set(codes)):
        raise ValueError("Candidate codes must be non-empty and unique.")
    if (
        not minimum_complex_improvement.is_finite()
        or not Decimal("0") <= minimum_complex_improvement <= Decimal("1")
    ):
        raise ValueError("Complex-model improvement must be between zero and one.")
    if len(values) != plan.series_length:
        raise ValueError("Values must match the chronological evaluation plan.")
    if not plan.folds:
        raise ValueError("Model selection requires validation folds.")

    evaluations: list[CandidateEvaluation] = []
    failures: list[CandidateFailure] = []
    available: dict[str, ForecastCandidate] = {}
    for candidate in candidates:
        if plan.folds[0].training_size < candidate.minimum_training_points:
            failures.append(
                CandidateFailure(
                    model_code=candidate.code,
                    reason=CandidateFailureReason.INSUFFICIENT_HISTORY,
                )
            )
            continue
        try:
            evaluation = evaluate_candidate(
                values=values,
                plan=plan,
                candidate=candidate,
            )
        except ForecastCandidateUnavailableError:
            reason = CandidateFailureReason.DEPENDENCY_UNAVAILABLE
        except ForecastCandidateFitError:
            reason = CandidateFailureReason.FIT_FAILED
        except (ForecastCandidateError, ValueError):
            reason = CandidateFailureReason.EVALUATION_FAILED
        else:
            evaluations.append(evaluation)
            available[candidate.code] = candidate
            continue
        failures.append(CandidateFailure(model_code=candidate.code, reason=reason))

    if not evaluations:
        raise ForecastCandidateFitError("No candidate produced validation evidence.")
    ranking_metric = (
        SelectionMetric.WAPE
        if evaluations[0].metrics.wape is not None
        else SelectionMetric.MAE
    )
    ordered = sorted(
        evaluations,
        key=lambda evaluation: (
            _ranking_error(evaluation, ranking_metric),
            0 if _is_baseline(evaluation.model_code) else 1,
            evaluation.model_code,
        ),
    )
    baselines = tuple(
        evaluation for evaluation in ordered if _is_baseline(evaluation.model_code)
    )
    best_baseline = baselines[0] if baselines else None
    selected = ordered[0]
    improvement: Decimal | None = None
    if best_baseline is not None and not _is_baseline(selected.model_code):
        baseline_error = _ranking_error(best_baseline, ranking_metric)
        complex_error = _ranking_error(selected, ranking_metric)
        improvement = _relative_improvement(baseline_error, complex_error)
        if improvement < minimum_complex_improvement:
            selected = best_baseline

    selected_candidate = available[selected.model_code]
    training = values[: plan.test_start]
    actual = values[plan.test_start : plan.test_end]
    if len(training) < selected_candidate.minimum_training_points or not actual:
        raise ForecastCandidateFitError("Selected candidate cannot evaluate final test.")
    predicted = selected_candidate.predict(training, len(actual))
    final_test = FinalTestEvaluation(
        actual=actual,
        predicted=predicted,
        metrics=calculate_forecast_error_metrics(
            actual=actual,
            predicted=predicted,
        ),
    )
    return ForecastModelSelection(
        policy_version=FORECAST_SELECTION_POLICY_VERSION,
        ranking_metric=ranking_metric,
        minimum_complex_improvement=minimum_complex_improvement.quantize(
            EVALUATION_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        ),
        selected_model_code=selected.model_code,
        selected_is_baseline=_is_baseline(selected.model_code),
        best_baseline_model_code=(
            best_baseline.model_code if best_baseline is not None else None
        ),
        complex_improvement_over_baseline=improvement,
        candidate_evaluations=tuple(evaluations),
        candidate_failures=tuple(failures),
        final_test=final_test,
    )


def _is_baseline(model_code: str) -> bool:
    return model_code in _BASELINE_CODES


def _ranking_error(
    evaluation: CandidateEvaluation, metric: SelectionMetric
) -> Decimal:
    if metric is SelectionMetric.WAPE:
        if evaluation.metrics.wape is None:
            raise ValueError("WAPE ranking requires non-zero validation actuals.")
        return evaluation.metrics.wape
    return evaluation.metrics.mae


def _relative_improvement(baseline: Decimal, candidate: Decimal) -> Decimal:
    if baseline == 0:
        return Decimal("0.000000")
    return ((baseline - candidate) / baseline).quantize(
        EVALUATION_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
