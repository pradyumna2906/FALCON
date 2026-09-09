"""Tests for validation-residual confidence calibration and forecast bands."""

from dataclasses import replace
from decimal import Decimal

import pytest

from falcon_api.forecasting import (
    FORECAST_UNCERTAINTY_POLICY_VERSION,
    CandidateEvaluation,
    ConfidenceCalibration,
    EvaluationFold,
    FoldEvaluation,
    ForecastErrorMetrics,
    ForecastUncertaintyCalibration,
    UncertaintyReliability,
    build_forecast_uncertainty,
    calibrate_forecast_uncertainty,
)


def _evaluation(count: int) -> CandidateEvaluation:
    actual = tuple(Decimal(100 + index) for index in range(count))
    predicted = tuple(
        actual[index] - Decimal(index + 1) for index in range(count)
    )
    return CandidateEvaluation(
        policy_version="2026.1",
        model_code="last_value",
        folds=(
            FoldEvaluation(
                fold=EvaluationFold(0, 3, 3, 3 + count),
                actual=actual,
                predicted=predicted,
            ),
        ),
        metrics=ForecastErrorMetrics(
            mae=Decimal("1"),
            rmse=Decimal("1"),
            wape=Decimal("0.1"),
            bias=Decimal("-1"),
            observation_count=count,
        ),
    )


def test_finite_sample_calibration_records_radius_and_empirical_coverage() -> None:
    result = calibrate_forecast_uncertainty(evaluation=_evaluation(10))
    assert result.policy_version == FORECAST_UNCERTAINTY_POLICY_VERSION
    assert result.model_code == "last_value"
    assert result.residual_count == 10
    assert result.reliability is UncertaintyReliability.NORMAL
    assert result.intervals == (
        ConfidenceCalibration(
            confidence_level=Decimal("0.800000"),
            absolute_error_radius=Decimal("9.0000"),
            empirical_coverage=Decimal("0.900000"),
        ),
        ConfidenceCalibration(
            confidence_level=Decimal("0.950000"),
            absolute_error_radius=Decimal("10.0000"),
            empirical_coverage=Decimal("1.000000"),
        ),
    )


def test_limited_validation_evidence_is_explicitly_provisional() -> None:
    result = calibrate_forecast_uncertainty(evaluation=_evaluation(2))
    assert result.reliability is UncertaintyReliability.PROVISIONAL
    assert result.residual_count == 2


def test_forecast_bands_are_nested_and_optionally_floored_at_zero() -> None:
    calibration = calibrate_forecast_uncertainty(evaluation=_evaluation(10))
    points = build_forecast_uncertainty(
        expected=(Decimal("5"), Decimal("20")),
        calibration=calibration,
        floor_at_zero=True,
    )
    assert points[0].step == 1
    assert points[0].expected == Decimal("5.0000")
    assert points[0].bands[0].lower == Decimal("0")
    assert points[0].bands[0].upper == Decimal("14.0000")
    assert points[0].bands[1].upper == Decimal("15.0000")
    assert points[1].bands[0].lower == Decimal("11.0000")

    signed = build_forecast_uncertainty(
        expected=(Decimal("5"),),
        calibration=calibration,
        floor_at_zero=False,
    )
    assert signed[0].bands[1].lower == Decimal("-5.0000")


@pytest.mark.parametrize(
    "levels",
    [
        (),
        (Decimal("0.8"), Decimal("0.8")),
        (Decimal("0.9"), Decimal("0.8")),
        (Decimal("0"),),
        (Decimal("1"),),
        (Decimal("NaN"),),
        (Decimal("0.8000001"), Decimal("0.8000002")),
    ],
)
def test_calibration_rejects_invalid_confidence_levels(
    levels: tuple[Decimal, ...],
) -> None:
    with pytest.raises(ValueError, match="Confidence levels"):
        calibrate_forecast_uncertainty(
            evaluation=_evaluation(2),
            confidence_levels=levels,
        )


def test_uncertainty_rejects_missing_residuals_and_unsafe_expected_values() -> None:
    empty = CandidateEvaluation(
        policy_version="2026.1",
        model_code="empty",
        folds=(),
        metrics=ForecastErrorMetrics(
            mae=Decimal("0"),
            rmse=Decimal("0"),
            wape=None,
            bias=Decimal("0"),
            observation_count=0,
        ),
    )
    with pytest.raises(ValueError, match="residuals"):
        calibrate_forecast_uncertainty(evaluation=empty)

    calibration = ForecastUncertaintyCalibration(
        policy_version="2026.1",
        model_code="last_value",
        residual_count=1,
        reliability=UncertaintyReliability.PROVISIONAL,
        intervals=(
            ConfidenceCalibration(
                confidence_level=Decimal("0.8"),
                absolute_error_radius=Decimal("1"),
                empirical_coverage=Decimal("1"),
            ),
        ),
    )
    for expected in ((), (Decimal("NaN"),)):
        with pytest.raises(ValueError, match="Expected"):
            build_forecast_uncertainty(
                expected=expected,
                calibration=calibration,
                floor_at_zero=False,
            )
    with pytest.raises(ValueError, match="boolean"):
        build_forecast_uncertainty(
            expected=(Decimal("1"),),
            calibration=calibration,
            floor_at_zero=1,  # type: ignore[arg-type]
        )

    evaluation = _evaluation(2)
    misaligned = replace(
        evaluation,
        folds=(replace(evaluation.folds[0], predicted=()),),
    )
    with pytest.raises(ValueError, match="aligned"):
        calibrate_forecast_uncertainty(evaluation=misaligned)
