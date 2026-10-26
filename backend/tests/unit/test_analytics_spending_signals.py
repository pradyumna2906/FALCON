"""Deterministic leak and anomaly policy coverage."""

from datetime import date
from decimal import Decimal

import pytest

from falcon_api.analytics.periods import AnalyticsPeriod
from falcon_api.analytics.spending_signals import (
    SpendingSignalEvaluationStatus,
    SpendingSignalFamily,
    SpendingSignalReasonCode,
    SpendingSignalSeverity,
    SpendingSignalType,
    detect_spending_signals,
)
from falcon_api.analytics.types import SpendingSignalTransactionRecord


_PERIOD = AnalyticsPeriod(
    date_from=date(2026, 4, 1),
    date_to=date(2026, 4, 28),
    timezone="Asia/Kolkata",
)


def _record(
    observed_date: date,
    amount: str,
    *,
    merchant: str | None = "merchant",
    code: str | None = "general_shopping",
    category: str | None = "General Shopping",
) -> SpendingSignalTransactionRecord:
    return SpendingSignalTransactionRecord(
        transaction_date=observed_date,
        amount=Decimal(amount),
        normalized_merchant=merchant.lower() if merchant is not None else None,
        display_name=merchant,
        classification_code=code,
        category_name=category,
    )


def _signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    *,
    period: AnalyticsPeriod = _PERIOD,
):
    return detect_spending_signals(
        records,
        period=period,
        total_expense=sum(
            (item.amount for item in records),
            start=Decimal("0"),
        ),
    )


def _of_type(analysis, signal_type: SpendingSignalType):
    return tuple(
        signal for signal in analysis.signals if signal.signal_type is signal_type
    )


def _evaluation(analysis, signal_type: SpendingSignalType):
    return next(
        item for item in analysis.evaluations if item.signal_type is signal_type
    )


def test_repeated_bank_charges_are_cautious_potential_leak() -> None:
    records = (
        _record(date(2026, 4, 2), "25", code="bank_charges", category="Bank Charges"),
        _record(date(2026, 4, 9), "50", code="bank_charges", category="Bank Charges"),
    )

    analysis = _signals(records)
    signal = _of_type(analysis, SpendingSignalType.BANK_CHARGE_LEAKAGE)[0]

    assert signal.family is SpendingSignalFamily.POTENTIAL_LEAK
    assert signal.observed_amount == Decimal("75.0000")
    assert signal.reason_codes == (
        SpendingSignalReasonCode.CANONICAL_BANK_CHARGE,
        SpendingSignalReasonCode.REPEATED_FREQUENCY,
    )
    assert "not a claim" in signal.explanation


def test_repeated_small_expenses_use_personal_relative_threshold() -> None:
    small = tuple(
        _record(date(2026, 4, day), "10", merchant="Tea Shop") for day in range(1, 6)
    )
    larger = tuple(
        _record(date(2026, 4, day), "100", merchant=f"Shop {day}")
        for day in range(6, 11)
    )

    signal = _of_type(
        _signals(small + larger),
        SpendingSignalType.REPEATED_SMALL_EXPENSES,
    )[0]

    assert signal.occurrence_count == 5
    assert signal.baseline_amount == Decimal("27.5000")
    assert signal.observed_amount == Decimal("50.0000")
    assert signal.normalized_merchant == "tea shop"


def test_regular_canonical_streaming_is_reviewable_not_unwanted() -> None:
    period = AnalyticsPeriod(
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 30),
        timezone="Asia/Kolkata",
    )
    records = tuple(
        _record(
            observed_date,
            "799",
            merchant="StreamCo",
            code="streaming",
            category="Streaming",
        )
        for observed_date in (
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
            date(2026, 4, 1),
        )
    )

    signal = _of_type(
        _signals(records, period=period),
        SpendingSignalType.RECURRING_SUBSCRIPTION,
    )[0]

    assert signal.evidence_score == Decimal("1.000000")
    assert signal.baseline_amount == Decimal("799.0000")
    assert "not assumed to be unwanted" in signal.explanation


def test_merchant_concentration_requires_count_and_thirty_percent_share() -> None:
    records = (
        _record(date(2026, 4, 1), "200", merchant="Big Merchant"),
        _record(date(2026, 4, 2), "200", merchant="Big Merchant"),
        _record(date(2026, 4, 3), "200", merchant="Big Merchant"),
        _record(date(2026, 4, 4), "50", merchant="A"),
        _record(date(2026, 4, 5), "50", merchant="B"),
        _record(date(2026, 4, 6), "50", merchant="C"),
    )

    signal = _of_type(
        _signals(records),
        SpendingSignalType.MERCHANT_CONCENTRATION,
    )[0]

    assert signal.share_of_total_expense == Decimal("0.800000")
    assert signal.severity is SpendingSignalSeverity.HIGH
    assert signal.baseline_amount == Decimal("225.0000")
    assert signal.excess_amount == Decimal("375.0000")


def test_category_spike_uses_three_prior_seven_day_robust_windows() -> None:
    records = (
        _record(date(2026, 4, 2), "100", merchant="Cafe", code="restaurants"),
        _record(date(2026, 4, 9), "100", merchant="Cafe", code="restaurants"),
        _record(date(2026, 4, 16), "100", merchant="Cafe", code="restaurants"),
        _record(date(2026, 4, 23), "500", merchant="Cafe", code="restaurants"),
    )

    signal = _of_type(
        _signals(records),
        SpendingSignalType.CATEGORY_SPIKE,
    )[0]

    assert signal.baseline_amount == Decimal("100.0000")
    assert signal.observed_amount == Decimal("500.0000")
    assert signal.excess_amount == Decimal("400.0000")
    assert SpendingSignalReasonCode.ABOVE_ROBUST_BASELINE in signal.reason_codes


def test_amount_outlier_uses_median_and_median_absolute_deviation() -> None:
    records = tuple(
        _record(date(2026, 4, day), amount, merchant="Grocer", code="groceries")
        for day, amount in enumerate(
            ("100", "100", "100", "100", "500"),
            start=1,
        )
    )

    signal = _of_type(
        _signals(records),
        SpendingSignalType.UNUSUAL_AMOUNT,
    )[0]

    assert signal.occurrence_count == 1
    assert signal.observed_amount == Decimal("500.0000")
    assert signal.baseline_amount == Decimal("100.0000")
    assert signal.excess_amount == Decimal("400.0000")
    assert signal.reason_codes[0] is SpendingSignalReasonCode.ROBUST_AMOUNT_OUTLIER


def test_discretionary_spike_aggregates_reviewed_category_codes() -> None:
    records = (
        _record(date(2026, 4, 2), "50", merchant="Cafe", code="restaurants"),
        _record(date(2026, 4, 9), "50", merchant="Cab", code="taxi_ride_share"),
        _record(date(2026, 4, 16), "50", merchant="Game", code="gaming"),
        _record(date(2026, 4, 23), "400", merchant="Shop", code="clothing"),
    )

    signal = _of_type(
        _signals(records),
        SpendingSignalType.DISCRETIONARY_SPIKE,
    )[0]

    assert signal.observed_amount == Decimal("400.0000")
    assert signal.baseline_amount == Decimal("50.0000")
    assert signal.classification_code == "clothing"
    assert SpendingSignalReasonCode.DISCRETIONARY_CATEGORY in signal.reason_codes


def test_duplicate_like_signal_never_claims_a_confirmed_duplicate() -> None:
    records = (
        _record(date(2026, 4, 8), "620", merchant="Food App"),
        _record(date(2026, 4, 8), "620", merchant="Food App"),
    )

    signal = _of_type(
        _signals(records),
        SpendingSignalType.DUPLICATE_LIKE_EXPENSE,
    )[0]

    assert signal.observed_amount == Decimal("1240.0000")
    assert signal.baseline_amount == Decimal("620.0000")
    assert signal.excess_amount == Decimal("620.0000")
    assert "manual review" in signal.explanation


def test_zero_data_explicitly_marks_every_check_insufficient() -> None:
    analysis = detect_spending_signals(
        (),
        period=_PERIOD,
        total_expense=Decimal("0"),
    )

    assert analysis.signals == ()
    assert {item.signal_type for item in analysis.evaluations} == set(
        SpendingSignalType
    )
    assert all(
        item.status is SpendingSignalEvaluationStatus.INSUFFICIENT_DATA
        for item in analysis.evaluations
    )


def test_no_signal_and_insufficient_states_are_distinct() -> None:
    records = tuple(
        _record(date(2026, 4, day), "100", merchant=f"Merchant {day}")
        for day in range(1, 6)
    )

    analysis = _signals(records)

    assert (
        _evaluation(
            analysis,
            SpendingSignalType.MERCHANT_CONCENTRATION,
        ).status
        is SpendingSignalEvaluationStatus.NO_SIGNAL
    )
    assert (
        _evaluation(
            analysis,
            SpendingSignalType.RECURRING_SUBSCRIPTION,
        ).status
        is SpendingSignalEvaluationStatus.INSUFFICIENT_DATA
    )


def test_invalid_total_or_source_record_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        detect_spending_signals(
            (),
            period=_PERIOD,
            total_expense=Decimal("-1"),
        )
    with pytest.raises(ValueError, match="positive and inside"):
        detect_spending_signals(
            (_record(date(2026, 3, 31), "10"),),
            period=_PERIOD,
            total_expense=Decimal("10"),
        )
