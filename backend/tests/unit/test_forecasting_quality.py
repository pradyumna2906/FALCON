"""Tests for explainable forecasting-history quality and eligibility."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from falcon_api.forecasting import (
    FORECAST_QUALITY_POLICY_VERSION,
    ForecastEligibility,
    ForecastGranularity,
    ForecastHistoryWindow,
    ForecastQualityReason,
    ForecastSourceBucket,
    ForecastTarget,
    assess_forecast_quality,
    build_forecast_series,
)


_CUTOFF = datetime(2026, 12, 31, 12, tzinfo=UTC)


def _monthly_series(
    values: tuple[str, ...], *, transactions_per_period: int
):  # type: ignore[no-untyped-def]
    starts = tuple(date(2026, month, 1) for month in range(1, len(values) + 1))
    end_start = starts[-1]
    next_month = date(end_start.year, end_start.month + 1, 1)
    window = ForecastHistoryWindow(
        date_from=starts[0],
        date_to=next_month - timedelta(days=1),
        timezone="UTC",
        granularity=ForecastGranularity.MONTH,
        data_cutoff_at=_CUTOFF,
    )
    buckets = tuple(
        ForecastSourceBucket(
            period_start=period_start,
            gross_income=Decimal(value),
            total_expense=Decimal("0"),
            transaction_count=transactions_per_period,
            source_last_updated_at=_CUTOFF,
        )
        for period_start, value in zip(starts, values)
    )
    return build_forecast_series(
        target=ForecastTarget.GROSS_INCOME,
        currency="INR",
        window=window,
        buckets=buckets,
    )


def test_three_usable_months_and_six_transactions_are_normal_eligible() -> None:
    assessment = assess_forecast_quality(
        _monthly_series(("1000", "1200", "1100"), transactions_per_period=2)
    )
    assert assessment.policy_version == FORECAST_QUALITY_POLICY_VERSION
    assert assessment.eligibility is ForecastEligibility.NORMAL
    assert assessment.calendar_period_count == 3
    assert assessment.observed_period_count == 3
    assert assessment.zero_filled_period_count == 0
    assert assessment.nonzero_period_count == 3
    assert assessment.transaction_count == 6
    assert assessment.zero_filled_ratio == Decimal("0.000000")
    assert assessment.reasons == (ForecastQualityReason.NORMAL_HISTORY,)


def test_limited_monthly_history_remains_provisional_with_reasons() -> None:
    assessment = assess_forecast_quality(
        _monthly_series(("1000", "1200"), transactions_per_period=1)
    )
    assert assessment.eligibility is ForecastEligibility.PROVISIONAL
    assert assessment.reasons[:3] == (
        ForecastQualityReason.LIMITED_HISTORY,
        ForecastQualityReason.LIMITED_OBSERVED_PERIODS,
        ForecastQualityReason.LIMITED_TRANSACTIONS,
    )


def test_no_eligible_activity_is_unavailable_and_zero_filled() -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 8, 31),
        timezone="UTC",
        granularity=ForecastGranularity.MONTH,
        data_cutoff_at=_CUTOFF,
    )
    series = build_forecast_series(
        target=ForecastTarget.TOTAL_EXPENSE,
        currency="INR",
        window=window,
        buckets=(),
    )
    assessment = assess_forecast_quality(series)
    assert assessment.eligibility is ForecastEligibility.UNAVAILABLE
    assert assessment.observed_period_count == 0
    assert assessment.zero_filled_ratio == Decimal("1.000000")
    assert assessment.relative_dispersion is None
    assert assessment.reasons == (
        ForecastQualityReason.NO_ELIGIBLE_ACTIVITY,
        ForecastQualityReason.SPARSE_ACTIVITY,
    )


def test_irregular_outlier_heavy_activity_is_reported_without_hiding_data() -> None:
    values = (
        "100",
        "110",
        "90",
        "105",
        "95",
        "100",
        "110",
        "1000",
        "1200",
        "100",
    )
    assessment = assess_forecast_quality(
        _monthly_series(values, transactions_per_period=2)
    )
    assert assessment.outlier_period_count == 2
    assert assessment.outlier_ratio == Decimal("0.200000")
    assert assessment.relative_dispersion is not None
    assert assessment.relative_dispersion > Decimal("1.000000")
    assert ForecastQualityReason.OUTLIER_HEAVY in assessment.reasons
    assert ForecastQualityReason.IRREGULAR_ACTIVITY in assessment.reasons


def test_daily_normal_threshold_requires_span_observations_and_transactions() -> None:
    window = ForecastHistoryWindow(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 8, 29),
        timezone="UTC",
        granularity=ForecastGranularity.DAY,
        data_cutoff_at=_CUTOFF,
    )
    buckets = tuple(
        ForecastSourceBucket(
            period_start=date(2026, 6, 1) + timedelta(days=index * 7),
            gross_income=Decimal("100"),
            total_expense=Decimal("0"),
            transaction_count=2,
            source_last_updated_at=_CUTOFF,
        )
        for index in range(12)
    )
    series = build_forecast_series(
        target=ForecastTarget.GROSS_INCOME,
        currency="INR",
        window=window,
        buckets=buckets,
    )
    assessment = assess_forecast_quality(series)
    assert assessment.eligibility is ForecastEligibility.NORMAL
    assert assessment.calendar_period_count == 90
    assert assessment.observed_period_count == 12
    assert assessment.transaction_count == 24
    assert ForecastQualityReason.SPARSE_ACTIVITY in assessment.reasons
