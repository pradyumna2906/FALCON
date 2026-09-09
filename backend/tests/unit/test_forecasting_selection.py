"""Tests for deterministic validation ranking and reserved-test evaluation."""

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from falcon_api.forecasting import (
    CandidateFailureReason,
    ChronologicalEvaluationPlan,
    ForecastCandidateFitError,
    ForecastCandidateUnavailableError,
    RollingOriginConfig,
    SelectionMetric,
    build_chronological_evaluation_plan,
    select_forecast_model,
)


@dataclass
class _DeltaCandidate:
    code: str
    delta: Decimal
    minimum_training_points: int = 1
    calls: list[tuple[Decimal, ...]] = field(default_factory=list)

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        self.calls.append(training_values)
        return tuple(training_values[-1] + self.delta for _ in range(horizon))


@dataclass
class _UnavailableCandidate:
    code: str = "prophet_month"
    minimum_training_points: int = 1

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        raise ForecastCandidateUnavailableError("missing")


def _plan(length: int = 8):
    return build_chronological_evaluation_plan(
        series_length=length,
        config=RollingOriginConfig(
            minimum_training_points=3,
            maximum_folds=3,
            test_size=1,
        ),
    )


def test_complex_model_must_beat_baseline_before_final_test_use() -> None:
    values = tuple(Decimal(value) for value in range(1, 9))
    baseline = _DeltaCandidate(code="last_value", delta=Decimal("0"))
    complex_candidate = _DeltaCandidate(
        code="xgboost_lagged_month", delta=Decimal("1")
    )
    result = select_forecast_model(
        values=values,
        plan=_plan(),
        candidates=(baseline, complex_candidate),
    )
    assert result.ranking_metric is SelectionMetric.WAPE
    assert result.selected_model_code == "xgboost_lagged_month"
    assert result.selected_is_baseline is False
    assert result.best_baseline_model_code == "last_value"
    assert result.complex_improvement_over_baseline == Decimal("1.000000")
    assert result.final_test.actual == (Decimal("8"),)
    assert result.final_test.predicted == (Decimal("8"),)
    assert result.final_test.metrics.mae == Decimal("0.000000")
    assert len(complex_candidate.calls) == 4
    assert all(Decimal("8") not in call for call in complex_candidate.calls)


def test_baseline_guardrail_rejects_immaterial_complex_improvement() -> None:
    values = tuple(Decimal(value) for value in range(1, 9))
    result = select_forecast_model(
        values=values,
        plan=_plan(),
        candidates=(
            _DeltaCandidate(code="last_value", delta=Decimal("0")),
            _DeltaCandidate(code="arima_1_1_1", delta=Decimal("0.04")),
        ),
    )
    assert result.selected_model_code == "last_value"
    assert result.complex_improvement_over_baseline == Decimal("0.040002")


def test_candidate_failures_are_isolated_and_recorded() -> None:
    values = tuple(Decimal(value) for value in range(1, 9))
    result = select_forecast_model(
        values=values,
        plan=_plan(),
        candidates=(
            _UnavailableCandidate(),
            _DeltaCandidate(
                code="seasonal_naive",
                delta=Decimal("0"),
                minimum_training_points=99,
            ),
            _DeltaCandidate(code="last_value", delta=Decimal("0")),
        ),
    )
    assert tuple(failure.reason for failure in result.candidate_failures) == (
        CandidateFailureReason.DEPENDENCY_UNAVAILABLE,
        CandidateFailureReason.INSUFFICIENT_HISTORY,
    )


def test_zero_actual_validation_uses_mae_instead_of_undefined_wape() -> None:
    values = (Decimal("0"),) * 8
    result = select_forecast_model(
        values=values,
        plan=_plan(),
        candidates=(_DeltaCandidate(code="last_value", delta=Decimal("0")),),
    )
    assert result.ranking_metric is SelectionMetric.MAE
    assert result.selected_model_code == "last_value"


@pytest.mark.parametrize("improvement", [Decimal("-0.1"), Decimal("1.1"), Decimal("NaN")])
def test_selection_rejects_invalid_policy_and_candidate_inputs(
    improvement: Decimal,
) -> None:
    values = tuple(Decimal(value) for value in range(1, 9))
    with pytest.raises(ValueError, match="improvement"):
        select_forecast_model(
            values=values,
            plan=_plan(),
            candidates=(_DeltaCandidate("last_value", Decimal("0")),),
            minimum_complex_improvement=improvement,
        )


def test_selection_rejects_empty_duplicate_misaligned_and_all_failed() -> None:
    values = tuple(Decimal(value) for value in range(1, 9))
    plan = _plan()
    with pytest.raises(ValueError, match="at least one"):
        select_forecast_model(values=values, plan=plan, candidates=())
    duplicate = _DeltaCandidate("last_value", Decimal("0"))
    with pytest.raises(ValueError, match="unique"):
        select_forecast_model(
            values=values,
            plan=plan,
            candidates=(duplicate, duplicate),
        )
    with pytest.raises(ValueError, match="match"):
        select_forecast_model(
            values=values[:-1],
            plan=plan,
            candidates=(duplicate,),
        )
    with pytest.raises(ForecastCandidateFitError, match="No candidate"):
        select_forecast_model(
            values=values,
            plan=plan,
            candidates=(_UnavailableCandidate(),),
        )
    with pytest.raises(ValueError, match="validation folds"):
        select_forecast_model(
            values=values,
            plan=ChronologicalEvaluationPlan(
                series_length=8,
                folds=(),
                test_start=7,
                test_end=8,
            ),
            candidates=(duplicate,),
        )
