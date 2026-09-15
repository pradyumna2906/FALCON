"""Forecast-to-savings-capacity bridge tests."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from falcon_api.goal_planning import CAPACITY_POLICY_VERSION, bridge_savings_forecast


def _run(
    *,
    target: str = "savings_amount",
    granularity: str = "month",
    periods: tuple[date, ...] = (date(2026, 10, 1), date(2026, 11, 1)),
    reliability: str = "normal",
):
    points = [
        SimpleNamespace(
            period_start=period,
            lower_95=Decimal("-100") if index == 0 else Decimal("200"),
            expected_value=Decimal("500") if index == 0 else Decimal("700"),
            upper_95=Decimal("900") if index == 0 else Decimal("1100"),
        )
        for index, period in enumerate(periods)
    ]
    return SimpleNamespace(
        id=uuid4(),
        target=target,
        granularity=granularity,
        currency="INR",
        uncertainty_reliability=reliability,
        points=points,
    )


def test_bridge_uses_95_percent_range_and_clips_negative_capacity() -> None:
    run = _run()

    result = bridge_savings_forecast(run, as_of=date(2026, 9, 14))

    assert result.forecast_run_id == run.id
    assert result.policy_version == CAPACITY_POLICY_VERSION == "2026.1"
    assert result.protection_band == "95_percent"
    assert result.points[0].protected_amount == Decimal("0.0000")
    assert result.protected_total == Decimal("200.0000")
    assert result.expected_total == Decimal("1200.0000")
    assert result.upside_total == Decimal("2000.0000")


def test_bridge_excludes_periods_before_snapshot_date() -> None:
    run = _run(periods=(date(2026, 8, 1), date(2026, 10, 1)))

    result = bridge_savings_forecast(run, as_of=date(2026, 9, 14))

    assert tuple(point.period_start for point in result.points) == (
        date(2026, 10, 1),
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"target": "total_expense"}, "savings forecast"),
        ({"granularity": "day"}, "monthly"),
        ({"periods": (date(2026, 8, 1),)}, "no future"),
    ],
)
def test_bridge_rejects_ineligible_forecast(change, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        bridge_savings_forecast(
            _run(**change),
            as_of=date(2026, 9, 14),
        )
