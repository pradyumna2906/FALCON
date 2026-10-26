"""Deterministic recurrence policy and abstention tests."""

from datetime import date
from decimal import Decimal

import pytest

from falcon_api.analytics.recurring import (
    RecurringCadence,
    RecurringConfidenceBand,
    RecurringDecision,
    RecurringPatternType,
    RecurringReasonCode,
    detect_recurring_patterns,
)
from falcon_api.analytics.types import RecurringTransactionRecord
from falcon_api.models.enums import TransactionType


def _record(
    observed: date,
    amount: str,
    *,
    merchant: str | None = "employer",
    display: str | None = "Employer",
    code: str | None = "salary",
    category: str | None = "Salary",
    transaction_type: TransactionType = TransactionType.INCOME,
) -> RecurringTransactionRecord:
    return RecurringTransactionRecord(
        transaction_date=observed,
        transaction_type=transaction_type,
        amount=Decimal(amount),
        normalized_merchant=merchant,
        display_name=display,
        classification_code=code,
        category_name=category,
    )


def test_monthly_salary_is_detected_with_exact_explainable_evidence() -> None:
    records = tuple(
        _record(observed, "50000")
        for observed in (
            date(2026, 5, 1),
            date(2026, 6, 1),
            date(2026, 7, 1),
            date(2026, 8, 1),
        )
    )

    result = detect_recurring_patterns(records)

    assert len(result) == 1
    pattern = result[0]
    assert pattern.pattern_type is RecurringPatternType.SALARY
    assert pattern.cadence is RecurringCadence.MONTHLY
    assert pattern.decision is RecurringDecision.DETECTED
    assert pattern.confidence == Decimal("1.000000")
    assert pattern.confidence_band is RecurringConfidenceBand.HIGH
    assert pattern.reason_codes == (
        RecurringReasonCode.CANONICAL_CATEGORY,
        RecurringReasonCode.REGULAR_INTERVAL,
        RecurringReasonCode.STABLE_AMOUNT,
    )
    assert pattern.median_interval_days == Decimal("31.00")
    assert pattern.median_amount == Decimal("50000.0000")
    assert pattern.observed_total == Decimal("200000.0000")
    assert "4 monthly salary transactions" in pattern.explanation
    assert "3/3 intervals" in pattern.explanation


@pytest.mark.parametrize(
    ("code", "expected_type"),
    [
        ("rent", RecurringPatternType.RENT),
        ("emi_loan_payment", RecurringPatternType.EMI),
        ("mutual_fund", RecurringPatternType.SIP),
        ("health_insurance", RecurringPatternType.INSURANCE),
        ("other_insurance", RecurringPatternType.INSURANCE),
        ("utilities", RecurringPatternType.UTILITIES),
        ("streaming", RecurringPatternType.SUBSCRIPTION),
    ],
)
def test_canonical_categories_assign_supported_recurring_meanings(
    code: str,
    expected_type: RecurringPatternType,
) -> None:
    records = tuple(
        _record(
            observed,
            amount,
            merchant=code,
            display=code.replace("_", " ").title(),
            code=code,
            category=code,
            transaction_type=TransactionType.EXPENSE,
        )
        for observed, amount in (
            (date(2026, 5, 5), "1000"),
            (date(2026, 6, 5), "1000"),
            (date(2026, 7, 5), "1000"),
        )
    )

    pattern = detect_recurring_patterns(records)[0]

    assert pattern.pattern_type is expected_type
    assert pattern.decision is RecurringDecision.DETECTED


def test_repeated_uncategorized_merchant_is_detected_without_type_guess() -> None:
    records = tuple(
        _record(
            observed,
            "799",
            merchant="reviewed merchant",
            display="Reviewed Merchant",
            code=None,
            category=None,
            transaction_type=TransactionType.EXPENSE,
        )
        for observed in (
            date(2026, 6, 2),
            date(2026, 6, 9),
            date(2026, 6, 16),
            date(2026, 6, 23),
        )
    )

    pattern = detect_recurring_patterns(records)[0]

    assert pattern.pattern_type is RecurringPatternType.REPEATED_MERCHANT
    assert pattern.cadence is RecurringCadence.WEEKLY
    assert pattern.reason_codes[0] is RecurringReasonCode.REPEATED_MERCHANT


def test_canonical_category_is_a_safe_fallback_when_merchant_is_missing() -> None:
    records = tuple(
        _record(
            observed,
            "50000",
            merchant=None,
            display=None,
        )
        for observed in (
            date(2026, 6, 1),
            date(2026, 7, 1),
            date(2026, 8, 1),
        )
    )

    pattern = detect_recurring_patterns(records)[0]

    assert pattern.pattern_type is RecurringPatternType.SALARY
    assert pattern.normalized_merchant is None
    assert pattern.classification_code == "salary"
    assert pattern.decision is RecurringDecision.DETECTED


def test_single_category_observation_does_not_label_a_whole_merchant_pattern() -> None:
    records = (
        _record(
            date(2026, 6, 1),
            "799",
            merchant="mixed",
            display="Mixed",
            code="streaming",
            category="Streaming",
            transaction_type=TransactionType.EXPENSE,
        ),
        _record(
            date(2026, 7, 1),
            "799",
            merchant="mixed",
            display="Mixed",
            code=None,
            category=None,
            transaction_type=TransactionType.EXPENSE,
        ),
        _record(
            date(2026, 8, 1),
            "799",
            merchant="mixed",
            display="Mixed",
            code=None,
            category=None,
            transaction_type=TransactionType.EXPENSE,
        ),
    )

    pattern = detect_recurring_patterns(records)[0]

    assert pattern.pattern_type is RecurringPatternType.REPEATED_MERCHANT
    assert pattern.classification_code is None
    assert pattern.reason_codes[0] is RecurringReasonCode.REPEATED_MERCHANT


def test_category_meaning_must_match_transaction_direction() -> None:
    records = tuple(
        _record(
            observed,
            "500",
            merchant="invalid salary direction",
            display="Invalid Salary Direction",
            code="salary",
            category="Salary",
            transaction_type=TransactionType.EXPENSE,
        )
        for observed in (
            date(2026, 6, 1),
            date(2026, 7, 1),
            date(2026, 8, 1),
        )
    )

    pattern = detect_recurring_patterns(records)[0]

    assert pattern.pattern_type is RecurringPatternType.REPEATED_MERCHANT
    assert pattern.reason_codes[0] is RecurringReasonCode.REPEATED_MERCHANT


def test_irregular_timing_abstains_instead_of_forcing_recurrence() -> None:
    records = tuple(
        _record(observed, "999")
        for observed in (
            date(2026, 1, 1),
            date(2026, 1, 3),
            date(2026, 2, 20),
            date(2026, 8, 1),
        )
    )

    pattern = detect_recurring_patterns(records)[0]

    assert pattern.cadence is RecurringCadence.IRREGULAR
    assert pattern.decision is RecurringDecision.ABSTAINED
    assert pattern.confidence_band is RecurringConfidenceBand.LOW
    assert RecurringReasonCode.IRREGULAR_INTERVAL in pattern.reason_codes
    assert "not consistent enough" in pattern.explanation


def test_unstable_amounts_can_force_abstention_despite_monthly_timing() -> None:
    records = tuple(
        _record(observed, amount, transaction_type=TransactionType.EXPENSE)
        for observed, amount in (
            (date(2026, 5, 1), "100"),
            (date(2026, 6, 1), "1000"),
            (date(2026, 7, 1), "1000"),
            (date(2026, 8, 1), "100"),
        )
    )

    pattern = detect_recurring_patterns(records)[0]

    assert pattern.cadence is RecurringCadence.MONTHLY
    assert pattern.confidence == Decimal("0.650000")
    assert pattern.decision is RecurringDecision.ABSTAINED
    assert RecurringReasonCode.VARIABLE_AMOUNT in pattern.reason_codes


def test_minimum_occurrences_and_unattributed_records_are_bounded() -> None:
    records = (
        _record(date(2026, 6, 1), "100"),
        _record(date(2026, 7, 1), "100"),
        _record(
            date(2026, 8, 1),
            "100",
            merchant=None,
            display=None,
            code=None,
            category=None,
        ),
    )

    assert detect_recurring_patterns(records) == ()
    with pytest.raises(ValueError, match="between 3 and 12"):
        detect_recurring_patterns(records, minimum_occurrences=2)
    with pytest.raises(ValueError, match="between 3 and 12"):
        detect_recurring_patterns(records, minimum_occurrences=True)


def test_same_day_payments_do_not_inflate_occurrence_count() -> None:
    records = (
        _record(date(2026, 7, 1), "100"),
        _record(date(2026, 7, 1), "200"),
        _record(date(2026, 8, 1), "300"),
    )

    assert detect_recurring_patterns(records) == ()


def test_patterns_sort_detected_before_abstained_then_by_evidence() -> None:
    detected = tuple(
        _record(
            observed,
            "500",
            merchant="stable",
            display="Stable",
            code=None,
            category=None,
            transaction_type=TransactionType.EXPENSE,
        )
        for observed in (
            date(2026, 5, 1),
            date(2026, 6, 1),
            date(2026, 7, 1),
        )
    )
    abstained = tuple(
        _record(
            observed,
            "5000",
            merchant="irregular",
            display="Irregular",
            code=None,
            category=None,
            transaction_type=TransactionType.EXPENSE,
        )
        for observed in (
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 8, 1),
        )
    )

    result = detect_recurring_patterns(abstained + detected)

    assert [item.decision for item in result] == [
        RecurringDecision.DETECTED,
        RecurringDecision.ABSTAINED,
    ]
