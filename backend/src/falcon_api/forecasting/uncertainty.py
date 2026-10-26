"""Validation-residual uncertainty calibration and bounded forecast intervals."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from falcon_api.analytics.types import money
from falcon_api.forecasting.evaluation import (
    EVALUATION_QUANTUM,
    CandidateEvaluation,
)


FORECAST_UNCERTAINTY_POLICY_VERSION = "2026.1"
DEFAULT_CONFIDENCE_LEVELS = (Decimal("0.800000"), Decimal("0.950000"))
MIN_NORMAL_CALIBRATION_RESIDUALS = 10


class UncertaintyReliability(StrEnum):
    PROVISIONAL = "provisional"
    NORMAL = "normal"


@dataclass(frozen=True, slots=True)
class ConfidenceCalibration:
    confidence_level: Decimal
    absolute_error_radius: Decimal
    empirical_coverage: Decimal


@dataclass(frozen=True, slots=True)
class ForecastUncertaintyCalibration:
    policy_version: str
    model_code: str
    residual_count: int
    reliability: UncertaintyReliability
    intervals: tuple[ConfidenceCalibration, ...]


@dataclass(frozen=True, slots=True)
class ForecastConfidenceBand:
    confidence_level: Decimal
    lower: Decimal
    upper: Decimal


@dataclass(frozen=True, slots=True)
class ForecastPointUncertainty:
    step: int
    expected: Decimal
    bands: tuple[ForecastConfidenceBand, ...]


def calibrate_forecast_uncertainty(
    *,
    evaluation: CandidateEvaluation,
    confidence_levels: tuple[Decimal, ...] = DEFAULT_CONFIDENCE_LEVELS,
) -> ForecastUncertaintyCalibration:
    """Calibrate finite-sample absolute-residual intervals on validation only."""
    levels = _validate_levels(confidence_levels)
    if any(
        not fold.actual or len(fold.actual) != len(fold.predicted)
        for fold in evaluation.folds
    ):
        raise ValueError("Uncertainty calibration requires aligned validation folds.")
    residuals = tuple(
        abs(actual - predicted)
        for fold in evaluation.folds
        for actual, predicted in zip(fold.actual, fold.predicted)
    )
    if not residuals or any(not residual.is_finite() for residual in residuals):
        raise ValueError("Uncertainty calibration requires finite validation residuals.")
    ordered = tuple(sorted(residuals))
    intervals = tuple(
        _calibrate_level(ordered=ordered, confidence_level=level)
        for level in levels
    )
    reliability = (
        UncertaintyReliability.NORMAL
        if len(residuals) >= MIN_NORMAL_CALIBRATION_RESIDUALS
        else UncertaintyReliability.PROVISIONAL
    )
    return ForecastUncertaintyCalibration(
        policy_version=FORECAST_UNCERTAINTY_POLICY_VERSION,
        model_code=evaluation.model_code,
        residual_count=len(residuals),
        reliability=reliability,
        intervals=intervals,
    )


def build_forecast_uncertainty(
    *,
    expected: tuple[Decimal, ...],
    calibration: ForecastUncertaintyCalibration,
    floor_at_zero: bool,
) -> tuple[ForecastPointUncertainty, ...]:
    """Apply calibrated radii without interpreting bands as guarantees."""
    if not isinstance(floor_at_zero, bool):
        raise ValueError("floor_at_zero must be boolean.")
    if not expected or any(not value.is_finite() for value in expected):
        raise ValueError("Expected forecast values must be non-empty and finite.")
    points: list[ForecastPointUncertainty] = []
    for step, value in enumerate(expected, start=1):
        normalized = money(value)
        bands = tuple(
            ForecastConfidenceBand(
                confidence_level=interval.confidence_level,
                lower=(
                    max(Decimal("0"), money(normalized - interval.absolute_error_radius))
                    if floor_at_zero
                    else money(normalized - interval.absolute_error_radius)
                ),
                upper=money(normalized + interval.absolute_error_radius),
            )
            for interval in calibration.intervals
        )
        points.append(
            ForecastPointUncertainty(
                step=step,
                expected=normalized,
                bands=bands,
            )
        )
    return tuple(points)


def _validate_levels(levels: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    if not levels or levels != tuple(sorted(set(levels))):
        raise ValueError("Confidence levels must be non-empty, unique, and ordered.")
    if any(not level.is_finite() or not Decimal("0") < level < Decimal("1") for level in levels):
        raise ValueError("Confidence levels must be finite values between zero and one.")
    quantized = tuple(
        level.quantize(EVALUATION_QUANTUM, rounding=ROUND_HALF_EVEN)
        for level in levels
    )
    if quantized != tuple(sorted(set(quantized))):
        raise ValueError("Confidence levels must remain unique at policy precision.")
    return quantized


def _calibrate_level(
    *, ordered: tuple[Decimal, ...], confidence_level: Decimal
) -> ConfidenceCalibration:
    count = len(ordered)
    rank = int(
        (confidence_level * Decimal(count + 1)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    radius = money(ordered[min(rank, count) - 1])
    covered = sum(residual <= radius for residual in ordered)
    empirical = (Decimal(covered) / Decimal(count)).quantize(
        EVALUATION_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
    return ConfidenceCalibration(
        confidence_level=confidence_level,
        absolute_error_radius=radius,
        empirical_coverage=empirical,
    )
