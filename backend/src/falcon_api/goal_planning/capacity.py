"""Cutoff-safe bridge from Phase 9 savings forecasts to planning capacity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from falcon_api.analytics.types import money
from falcon_api.forecasting.semantics import ForecastGranularity, ForecastTarget
from falcon_api.models.forecasting import ForecastRun


CAPACITY_POLICY_VERSION = "2026.1"


@dataclass(frozen=True, slots=True)
class SavingsCapacityPoint:
    """One monthly savings range clipped at zero for allocation safety."""

    period_start: date
    protected_amount: Decimal
    expected_amount: Decimal
    upside_amount: Decimal


@dataclass(frozen=True, slots=True)
class SavingsCapacityPlan:
    """Monthly capacity evidence derived from one immutable forecast run."""

    forecast_run_id: UUID
    currency: str
    policy_version: str
    protection_band: str
    reliability: str
    points: tuple[SavingsCapacityPoint, ...]
    protected_total: Decimal
    expected_total: Decimal
    upside_total: Decimal


def bridge_savings_forecast(
    run: ForecastRun,
    *,
    as_of: date,
) -> SavingsCapacityPlan:
    """Convert a monthly savings forecast into non-negative capacity ranges."""
    if run.target != ForecastTarget.SAVINGS_AMOUNT.value:
        raise ValueError("Planning capacity requires a savings forecast.")
    if run.granularity != ForecastGranularity.MONTH.value:
        raise ValueError("Planning capacity requires monthly forecast points.")
    eligible = tuple(point for point in run.points if point.period_start >= as_of)
    if not eligible:
        raise ValueError("The savings forecast has no future planning periods.")

    points = tuple(
        SavingsCapacityPoint(
            period_start=point.period_start,
            protected_amount=_non_negative(point.lower_95),
            expected_amount=_non_negative(point.expected_value),
            upside_amount=_non_negative(point.upper_95),
        )
        for point in eligible
    )
    return SavingsCapacityPlan(
        forecast_run_id=run.id,
        currency=run.currency,
        policy_version=CAPACITY_POLICY_VERSION,
        protection_band="95_percent",
        reliability=run.uncertainty_reliability,
        points=points,
        protected_total=money(
            sum((point.protected_amount for point in points), Decimal(0))
        ),
        expected_total=money(
            sum((point.expected_amount for point in points), Decimal(0))
        ),
        upside_total=money(sum((point.upside_amount for point in points), Decimal(0))),
    )


def _non_negative(value: Decimal) -> Decimal:
    return money(max(Decimal("0"), Decimal(value)))
