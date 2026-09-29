"""Tests for future analytics request and response contracts."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from falcon_api.analytics.periods import AnalyticsPeriod
from falcon_api.analytics.semantics import AnalyticsConfidenceLevel
from falcon_api.schemas.analytics import (
    AnalyticsCompleteness,
    AnalyticsContext,
    AnalyticsExclusions,
    AnalyticsFreshness,
    AnalyticsPeriodResponse,
    AnalyticsRangeQuery,
    MoneyMetric,
    RateMetric,
)


def _exclusions() -> AnalyticsExclusions:
    return AnalyticsExclusions(
        pending_count=2,
        transfer_entry_count=4,
        adjustment_count=1,
        other_currency_count=3,
    )


def test_range_query_defaults_and_normalizes_currency() -> None:
    query = AnalyticsRangeQuery(currency="inr")

    assert query.date_from is None
    assert query.date_to is None
    assert query.currency == "INR"
    assert query.comparison.value == "previous_period"
    assert set(query.model_json_schema()["properties"]) == {
        "date_from",
        "date_to",
        "currency",
        "comparison",
    }


@pytest.mark.parametrize(
    "values",
    [
        {"date_from": date(2026, 8, 1)},
        {"date_to": date(2026, 8, 1)},
        {"date_from": date(2026, 8, 2), "date_to": date(2026, 8, 1)},
        {"date_from": date(2025, 1, 1), "date_to": date(2026, 1, 2)},
        {"date_from": date.min, "date_to": date.min},
        {"currency": "RUPEE"},
    ],
)
def test_range_query_rejects_ambiguous_or_unbounded_input(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AnalyticsRangeQuery.model_validate(values)


def test_period_response_requires_consistent_inclusive_day_count() -> None:
    period = AnalyticsPeriod(
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        timezone="Asia/Kolkata",
    )

    response = AnalyticsPeriodResponse.from_period(period)

    assert response.day_count == 31
    with pytest.raises(ValidationError, match="day_count"):
        response.model_copy(update={"day_count": 30}).model_validate(
            response.model_dump() | {"day_count": 30}
        )


def test_freshness_requires_ordered_utc_timestamps() -> None:
    calculated = datetime(2026, 8, 24, 10, tzinfo=timezone.utc)
    freshness = AnalyticsFreshness(
        calculated_at=calculated,
        source_last_updated_at=calculated - timedelta(minutes=2),
        latest_transaction_date=date(2026, 8, 24),
    )

    assert freshness.materialized is False
    with pytest.raises(ValidationError, match="later than"):
        AnalyticsFreshness(
            calculated_at=calculated,
            source_last_updated_at=calculated + timedelta(seconds=1),
            latest_transaction_date=None,
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        AnalyticsFreshness(
            calculated_at=datetime(2026, 8, 24, 10),
            source_last_updated_at=None,
            latest_transaction_date=None,
        )


def test_completeness_computes_coverage_and_non_probability_confidence() -> None:
    completeness = AnalyticsCompleteness(
        eligible_transaction_count=40,
        categorized_transaction_count=36,
        suggested_transaction_count=2,
        abstained_transaction_count=1,
        exclusions=_exclusions(),
    )

    assert completeness.classification_coverage == Decimal("0.900000")
    assert completeness.data_confidence is AnalyticsConfidenceLevel.HIGH
    dumped = completeness.model_dump(mode="json")
    assert dumped["classification_coverage"] == "0.900000"
    assert dumped["data_confidence"] == "high"


@pytest.mark.parametrize(
    "values",
    [
        {
            "eligible_transaction_count": 1,
            "categorized_transaction_count": 2,
            "suggested_transaction_count": 0,
            "abstained_transaction_count": 0,
        },
        {
            "eligible_transaction_count": 5,
            "categorized_transaction_count": 4,
            "suggested_transaction_count": 1,
            "abstained_transaction_count": 1,
        },
    ],
)
def test_completeness_rejects_impossible_subsets(values: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        AnalyticsCompleteness(**values, exclusions=_exclusions())


def test_context_excludes_owner_and_carries_version_currency_and_quality() -> None:
    calculated = datetime(2026, 8, 24, 10, tzinfo=timezone.utc)
    period = AnalyticsPeriodResponse(
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 24),
        timezone="Asia/Kolkata",
        day_count=24,
    )
    context = AnalyticsContext(
        currency="inr",
        period=period,
        comparison_period=None,
        freshness=AnalyticsFreshness(
            calculated_at=calculated,
            source_last_updated_at=None,
            latest_transaction_date=None,
        ),
        completeness=AnalyticsCompleteness(
            eligible_transaction_count=0,
            categorized_transaction_count=0,
            suggested_transaction_count=0,
            abstained_transaction_count=0,
            exclusions=_exclusions(),
        ),
    )

    assert context.contract_version == "2026.1"
    assert context.currency == "INR"
    assert context.completeness.classification_coverage is None
    assert context.completeness.data_confidence.value == "unavailable"
    properties = set(AnalyticsContext.model_json_schema()["properties"])
    assert "user_id" not in properties
    assert "timezone_override" not in properties


@pytest.mark.parametrize("invalid_relationship", ["timezone", "range", "freshness"])
def test_context_rejects_inconsistent_period_metadata(
    invalid_relationship: str,
) -> None:
    calculated = datetime(2026, 8, 24, 10, tzinfo=timezone.utc)
    period = AnalyticsPeriodResponse(
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 24),
        timezone="Asia/Kolkata",
        day_count=15,
    )
    comparison = AnalyticsPeriodResponse(
        date_from=date(2026, 7, 26),
        date_to=date(2026, 8, 9),
        timezone=("UTC" if invalid_relationship == "timezone" else "Asia/Kolkata"),
        day_count=15,
    )
    if invalid_relationship == "range":
        comparison = AnalyticsPeriodResponse(
            date_from=date(2026, 7, 25),
            date_to=date(2026, 8, 8),
            timezone="Asia/Kolkata",
            day_count=15,
        )
    latest_date = (
        date(2026, 8, 25)
        if invalid_relationship == "freshness"
        else date(2026, 8, 24)
    )

    with pytest.raises(ValidationError):
        AnalyticsContext(
            currency="INR",
            period=period,
            comparison_period=comparison,
            freshness=AnalyticsFreshness(
                calculated_at=calculated,
                source_last_updated_at=None,
                latest_transaction_date=latest_date,
            ),
            completeness=AnalyticsCompleteness(
                eligible_transaction_count=0,
                categorized_transaction_count=0,
                suggested_transaction_count=0,
                abstained_transaction_count=0,
                exclusions=_exclusions(),
            ),
        )


def test_money_and_rate_contracts_normalize_exact_decimal_scales() -> None:
    money = MoneyMetric(value=Decimal("1234.5"))
    rate = RateMetric(value=Decimal("0.125"))
    unavailable = RateMetric(value=None)

    assert money.model_dump(mode="json")["value"] == "1234.5000"
    assert rate.model_dump(mode="json")["value"] == "0.125000"
    assert unavailable.value is None
