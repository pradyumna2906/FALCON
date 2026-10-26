"""Leakage-safe rolling-origin evaluation and exact forecast-error metrics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Protocol


FORECAST_EVALUATION_POLICY_VERSION = "2026.1"
EVALUATION_QUANTUM = Decimal("0.000001")


class ForecastCandidate(Protocol):
    """Stable prediction interface shared by every Phase 9 candidate."""

    code: str
    minimum_training_points: int

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]: ...


@dataclass(frozen=True, slots=True)
class RollingOriginConfig:
    """Bounds for expanding-window validation with a final untouched test set."""

    minimum_training_points: int
    validation_horizon: int = 1
    step: int = 1
    test_size: int = 1
    maximum_folds: int = 12

    def __post_init__(self) -> None:
        for value in (
            self.minimum_training_points,
            self.validation_horizon,
            self.step,
            self.test_size,
            self.maximum_folds,
        ):
            if isinstance(value, bool) or value <= 0:
                raise ValueError("Evaluation configuration values must be positive.")


@dataclass(frozen=True, slots=True)
class EvaluationFold:
    """Index boundary for one expanding training and later validation window."""

    train_start: int
    train_end: int
    validation_start: int
    validation_end: int

    @property
    def training_size(self) -> int:
        return self.train_end - self.train_start


@dataclass(frozen=True, slots=True)
class ChronologicalEvaluationPlan:
    """Validation folds plus a final range reserved from model ranking."""

    series_length: int
    folds: tuple[EvaluationFold, ...]
    test_start: int
    test_end: int


@dataclass(frozen=True, slots=True)
class ForecastErrorMetrics:
    """Exact aggregate errors; WAPE is null when actual magnitude is zero."""

    mae: Decimal
    rmse: Decimal
    wape: Decimal | None
    bias: Decimal
    observation_count: int


@dataclass(frozen=True, slots=True)
class FoldEvaluation:
    """Actual and predicted values for one auditable validation fold."""

    fold: EvaluationFold
    actual: tuple[Decimal, ...]
    predicted: tuple[Decimal, ...]


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """One candidate's rolling-origin evidence without touching test history."""

    policy_version: str
    model_code: str
    folds: tuple[FoldEvaluation, ...]
    metrics: ForecastErrorMetrics


def build_chronological_evaluation_plan(
    *, series_length: int, config: RollingOriginConfig
) -> ChronologicalEvaluationPlan:
    """Build latest bounded folds strictly before the reserved test window."""
    if isinstance(series_length, bool) or series_length <= 0:
        raise ValueError("series_length must be positive.")
    test_start = series_length - config.test_size
    last_validation_start = test_start - config.validation_horizon
    if last_validation_start < config.minimum_training_points:
        raise ValueError("Series is too short for training, validation, and test.")
    descending_starts = tuple(
        range(
            last_validation_start,
            config.minimum_training_points - 1,
            -config.step,
        )
    )
    starts = tuple(reversed(descending_starts[: config.maximum_folds]))
    folds = tuple(
        EvaluationFold(
            train_start=0,
            train_end=start,
            validation_start=start,
            validation_end=start + config.validation_horizon,
        )
        for start in starts
    )
    return ChronologicalEvaluationPlan(
        series_length=series_length,
        folds=folds,
        test_start=test_start,
        test_end=series_length,
    )


def calculate_forecast_error_metrics(
    *, actual: tuple[Decimal, ...], predicted: tuple[Decimal, ...]
) -> ForecastErrorMetrics:
    """Calculate MAE, RMSE, WAPE, and signed mean error deterministically."""
    if not actual or len(actual) != len(predicted):
        raise ValueError("Actual and predicted values must be non-empty and aligned.")
    if any(not value.is_finite() for value in (*actual, *predicted)):
        raise ValueError("Evaluation values must be finite.")
    errors = tuple(forecast - observed for observed, forecast in zip(actual, predicted))
    count = Decimal(len(errors))
    mae = sum(abs(error) for error in errors) / count
    mean_squared_error = sum(error**2 for error in errors) / count
    with localcontext() as context:
        context.prec = 28
        rmse = mean_squared_error.sqrt()
    actual_magnitude = sum(abs(value) for value in actual)
    wape = (
        None
        if actual_magnitude == 0
        else sum(abs(error) for error in errors) / actual_magnitude
    )
    bias = sum(errors) / count
    return ForecastErrorMetrics(
        mae=_quantize(mae),
        rmse=_quantize(rmse),
        wape=_quantize(wape) if wape is not None else None,
        bias=_quantize(bias),
        observation_count=len(errors),
    )


def evaluate_candidate(
    *,
    values: tuple[Decimal, ...],
    plan: ChronologicalEvaluationPlan,
    candidate: ForecastCandidate,
) -> CandidateEvaluation:
    """Evaluate one candidate on validation only; never expose test observations."""
    if len(values) != plan.series_length:
        raise ValueError("Values must match the chronological evaluation plan.")
    evaluated: list[FoldEvaluation] = []
    all_actual: list[Decimal] = []
    all_predicted: list[Decimal] = []
    for fold in plan.folds:
        if fold.validation_end > plan.test_start:
            raise ValueError("Validation folds must not overlap the reserved test set.")
        if fold.training_size < candidate.minimum_training_points:
            raise ValueError("Candidate requires more training observations.")
        training = values[fold.train_start : fold.train_end]
        actual = values[fold.validation_start : fold.validation_end]
        predicted = candidate.predict(training, len(actual))
        if len(predicted) != len(actual):
            raise ValueError("Candidate returned an invalid prediction horizon.")
        if any(not value.is_finite() for value in predicted):
            raise ValueError("Candidate returned a non-finite prediction.")
        evaluated.append(
            FoldEvaluation(fold=fold, actual=actual, predicted=predicted)
        )
        all_actual.extend(actual)
        all_predicted.extend(predicted)
    return CandidateEvaluation(
        policy_version=FORECAST_EVALUATION_POLICY_VERSION,
        model_code=candidate.code,
        folds=tuple(evaluated),
        metrics=calculate_forecast_error_metrics(
            actual=tuple(all_actual),
            predicted=tuple(all_predicted),
        ),
    )


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(EVALUATION_QUANTUM, rounding=ROUND_HALF_EVEN)
