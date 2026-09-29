"""Tests for rolling-origin planning and exact error metrics."""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from falcon_api.forecasting import (
    FORECAST_EVALUATION_POLICY_VERSION,
    ChronologicalEvaluationPlan,
    EvaluationFold,
    LastValueBaseline,
    RollingOriginConfig,
    build_chronological_evaluation_plan,
    calculate_forecast_error_metrics,
    evaluate_candidate,
)


def test_plan_uses_expanding_folds_and_reserves_final_test_history() -> None:
    plan = build_chronological_evaluation_plan(
        series_length=10,
        config=RollingOriginConfig(
            minimum_training_points=3,
            validation_horizon=2,
            step=2,
            test_size=2,
            maximum_folds=2,
        ),
    )
    assert plan == ChronologicalEvaluationPlan(
        series_length=10,
        folds=(
            EvaluationFold(0, 4, 4, 6),
            EvaluationFold(0, 6, 6, 8),
        ),
        test_start=8,
        test_end=10,
    )
    assert all(fold.validation_end <= plan.test_start for fold in plan.folds)


def test_plan_keeps_only_the_latest_bounded_folds() -> None:
    plan = build_chronological_evaluation_plan(
        series_length=12,
        config=RollingOriginConfig(
            minimum_training_points=3,
            test_size=1,
            maximum_folds=3,
        ),
    )
    assert tuple(fold.validation_start for fold in plan.folds) == (8, 9, 10)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minimum_training_points": 0},
        {"minimum_training_points": 1, "validation_horizon": 0},
        {"minimum_training_points": 1, "step": True},
        {"minimum_training_points": 1, "test_size": 0},
        {"minimum_training_points": 1, "maximum_folds": -1},
    ],
)
def test_evaluation_configuration_requires_positive_integers(
    kwargs: dict[str, int]
) -> None:
    with pytest.raises(ValueError, match="positive"):
        RollingOriginConfig(**kwargs)


def test_plan_rejects_invalid_or_insufficient_series() -> None:
    config = RollingOriginConfig(minimum_training_points=3, test_size=2)
    for series_length in (0, True):
        with pytest.raises(ValueError, match="series_length"):
            build_chronological_evaluation_plan(
                series_length=series_length,  # type: ignore[arg-type]
                config=config,
            )
    with pytest.raises(ValueError, match="too short"):
        build_chronological_evaluation_plan(series_length=5, config=config)


def test_error_metrics_have_fixed_direction_and_zero_safe_wape() -> None:
    metrics = calculate_forecast_error_metrics(
        actual=(Decimal("10"), Decimal("20")),
        predicted=(Decimal("12"), Decimal("16")),
    )
    assert metrics.mae == Decimal("3.000000")
    assert metrics.rmse == Decimal("3.162278")
    assert metrics.wape == Decimal("0.200000")
    assert metrics.bias == Decimal("-1.000000")
    assert metrics.observation_count == 2

    zero_actual = calculate_forecast_error_metrics(
        actual=(Decimal("0"),), predicted=(Decimal("1"),)
    )
    assert zero_actual.wape is None


def test_error_metrics_reject_misaligned_empty_and_nonfinite_values() -> None:
    for actual, predicted in (
        ((), ()),
        ((Decimal("1"),), ()),
        ((Decimal("NaN"),), (Decimal("1"),)),
    ):
        with pytest.raises(ValueError):
            calculate_forecast_error_metrics(actual=actual, predicted=predicted)


def test_candidate_evaluation_uses_training_only_and_never_reserved_test() -> None:
    values = tuple(Decimal(value) for value in range(1, 9))
    plan = build_chronological_evaluation_plan(
        series_length=len(values),
        config=RollingOriginConfig(
            minimum_training_points=3,
            test_size=1,
            maximum_folds=2,
        ),
    )
    result = evaluate_candidate(
        values=values,
        plan=plan,
        candidate=LastValueBaseline(),
    )
    assert result.policy_version == FORECAST_EVALUATION_POLICY_VERSION
    assert result.model_code == "last_value"
    assert tuple(fold.actual for fold in result.folds) == (
        (Decimal("6"),),
        (Decimal("7"),),
    )
    assert tuple(fold.predicted for fold in result.folds) == (
        (Decimal("5.0000"),),
        (Decimal("6.0000"),),
    )
    assert result.metrics.mae == Decimal("1.000000")
    assert Decimal("8") not in tuple(
        value for fold in result.folds for value in fold.actual
    )


@dataclass(frozen=True)
class _BrokenCandidate:
    code: str = "broken"
    minimum_training_points: int = 1
    prediction: tuple[Decimal, ...] = ()

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        return self.prediction


def test_candidate_evaluation_rejects_invalid_boundaries_and_predictions() -> None:
    values = tuple(Decimal(value) for value in range(1, 7))
    plan = build_chronological_evaluation_plan(
        series_length=6,
        config=RollingOriginConfig(minimum_training_points=3, test_size=1),
    )
    with pytest.raises(ValueError, match="match"):
        evaluate_candidate(
            values=values[:-1], plan=plan, candidate=LastValueBaseline()
        )
    overlapping = ChronologicalEvaluationPlan(
        series_length=6,
        folds=(EvaluationFold(0, 3, 3, 6),),
        test_start=5,
        test_end=6,
    )
    with pytest.raises(ValueError, match="overlap"):
        evaluate_candidate(
            values=values, plan=overlapping, candidate=LastValueBaseline()
        )
    with pytest.raises(ValueError, match="invalid prediction horizon"):
        evaluate_candidate(values=values, plan=plan, candidate=_BrokenCandidate())
    with pytest.raises(ValueError, match="non-finite"):
        evaluate_candidate(
            values=values,
            plan=plan,
            candidate=_BrokenCandidate(prediction=(Decimal("NaN"),)),
        )


def test_candidate_minimum_training_requirement_is_enforced() -> None:
    values = tuple(Decimal(value) for value in range(1, 7))
    plan = build_chronological_evaluation_plan(
        series_length=6,
        config=RollingOriginConfig(minimum_training_points=3, test_size=1),
    )
    with pytest.raises(ValueError, match="more training"):
        evaluate_candidate(
            values=values,
            plan=plan,
            candidate=_BrokenCandidate(minimum_training_points=4),
        )
