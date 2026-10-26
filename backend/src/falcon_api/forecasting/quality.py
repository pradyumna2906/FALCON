"""Deterministic data-quality evidence and forecast eligibility policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from statistics import median

from falcon_api.forecasting.semantics import (
    MIN_NORMAL_HISTORY_MONTHS,
    ForecastGranularity,
)
from falcon_api.forecasting.types import ForecastSeries


FORECAST_QUALITY_POLICY_VERSION = "2026.1"
MIN_NORMAL_HISTORY_DAYS = 90
MIN_NORMAL_MONTHLY_OBSERVED_PERIODS = 3
MIN_NORMAL_DAILY_OBSERVED_PERIODS = 12
MIN_NORMAL_MONTHLY_TRANSACTIONS = 6
MIN_NORMAL_DAILY_TRANSACTIONS = 20
SPARSE_ACTIVITY_RATIO = Decimal("0.700000")
IRREGULAR_DISPERSION_RATIO = Decimal("1.000000")
OUTLIER_RATIO_WARNING = Decimal("0.200000")
RATIO_QUANTUM = Decimal("0.000001")


class ForecastEligibility(StrEnum):
    """Whether the available source history can support candidate evaluation."""

    UNAVAILABLE = "unavailable"
    PROVISIONAL = "provisional"
    NORMAL = "normal"


class ForecastQualityReason(StrEnum):
    """Stable reason codes describing forecast-history sufficiency and risk."""

    NO_ELIGIBLE_ACTIVITY = "no_eligible_activity"
    LIMITED_HISTORY = "limited_history"
    LIMITED_OBSERVED_PERIODS = "limited_observed_periods"
    LIMITED_TRANSACTIONS = "limited_transactions"
    SPARSE_ACTIVITY = "sparse_activity"
    OUTLIER_HEAVY = "outlier_heavy"
    IRREGULAR_ACTIVITY = "irregular_activity"
    NORMAL_HISTORY = "normal_history"


@dataclass(frozen=True, slots=True)
class ForecastQualityAssessment:
    """Explainable source evidence; this is not model confidence."""

    policy_version: str
    eligibility: ForecastEligibility
    calendar_period_count: int
    observed_period_count: int
    zero_filled_period_count: int
    nonzero_period_count: int
    transaction_count: int
    outlier_period_count: int
    zero_filled_ratio: Decimal
    outlier_ratio: Decimal
    relative_dispersion: Decimal | None
    reasons: tuple[ForecastQualityReason, ...]


def assess_forecast_quality(series: ForecastSeries) -> ForecastQualityAssessment:
    """Assess sufficiency and variability without fitting or selecting a model."""
    values = tuple(point.value for point in series.points)
    period_count = len(values)
    observed_count = series.observed_period_count
    zero_filled_count = period_count - observed_count
    nonzero_count = sum(value != 0 for value in values)
    transaction_count = series.transaction_count
    outlier_count = _outlier_count(values)
    zero_filled_ratio = _ratio(zero_filled_count, period_count)
    outlier_ratio = _ratio(outlier_count, period_count)
    dispersion = _relative_dispersion(values)
    reasons: list[ForecastQualityReason] = []

    if transaction_count == 0:
        eligibility = ForecastEligibility.UNAVAILABLE
        reasons.append(ForecastQualityReason.NO_ELIGIBLE_ACTIVITY)
    else:
        (
            required_periods,
            required_observed,
            required_transactions,
        ) = _normal_thresholds(series.granularity)
        if period_count < required_periods:
            reasons.append(ForecastQualityReason.LIMITED_HISTORY)
        if observed_count < required_observed:
            reasons.append(ForecastQualityReason.LIMITED_OBSERVED_PERIODS)
        if transaction_count < required_transactions:
            reasons.append(ForecastQualityReason.LIMITED_TRANSACTIONS)
        eligibility = (
            ForecastEligibility.NORMAL
            if not reasons
            else ForecastEligibility.PROVISIONAL
        )
        if eligibility is ForecastEligibility.NORMAL:
            reasons.append(ForecastQualityReason.NORMAL_HISTORY)

    if zero_filled_ratio > SPARSE_ACTIVITY_RATIO:
        reasons.append(ForecastQualityReason.SPARSE_ACTIVITY)
    if outlier_count >= 2 and outlier_ratio >= OUTLIER_RATIO_WARNING:
        reasons.append(ForecastQualityReason.OUTLIER_HEAVY)
    if dispersion is not None and dispersion > IRREGULAR_DISPERSION_RATIO:
        reasons.append(ForecastQualityReason.IRREGULAR_ACTIVITY)

    return ForecastQualityAssessment(
        policy_version=FORECAST_QUALITY_POLICY_VERSION,
        eligibility=eligibility,
        calendar_period_count=period_count,
        observed_period_count=observed_count,
        zero_filled_period_count=zero_filled_count,
        nonzero_period_count=nonzero_count,
        transaction_count=transaction_count,
        outlier_period_count=outlier_count,
        zero_filled_ratio=zero_filled_ratio,
        outlier_ratio=outlier_ratio,
        relative_dispersion=dispersion,
        reasons=tuple(reasons),
    )


def _normal_thresholds(
    granularity: ForecastGranularity,
) -> tuple[int, int, int]:
    if ForecastGranularity(granularity) is ForecastGranularity.MONTH:
        return (
            MIN_NORMAL_HISTORY_MONTHS,
            MIN_NORMAL_MONTHLY_OBSERVED_PERIODS,
            MIN_NORMAL_MONTHLY_TRANSACTIONS,
        )
    return (
        MIN_NORMAL_HISTORY_DAYS,
        MIN_NORMAL_DAILY_OBSERVED_PERIODS,
        MIN_NORMAL_DAILY_TRANSACTIONS,
    )


def _ratio(numerator: int, denominator: int) -> Decimal:
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _outlier_count(values: tuple[Decimal, ...]) -> int:
    if len(values) < 5:
        return 0
    center = median(values)
    deviations = tuple(abs(value - center) for value in values)
    mad = median(deviations)
    if mad == 0:
        return 0
    threshold = Decimal("4.4478") * mad
    return sum(deviation > threshold for deviation in deviations)


def _relative_dispersion(values: tuple[Decimal, ...]) -> Decimal | None:
    mean_absolute = sum(abs(value) for value in values) / Decimal(len(values))
    if mean_absolute == 0:
        return None
    mean = sum(values) / Decimal(len(values))
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    with localcontext() as context:
        context.prec = 28
        dispersion = variance.sqrt() / mean_absolute
    return dispersion.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_EVEN)
