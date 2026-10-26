"""Deterministic recurring-transaction evidence and abstention policy."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from enum import StrEnum

from falcon_api.analytics.semantics import RATIO_QUANTUM
from falcon_api.analytics.types import RecurringTransactionRecord, money
from falcon_api.classification.taxonomy import ClassificationSubcategoryCode
from falcon_api.models.enums import TransactionType


MIN_RECURRING_OCCURRENCES = 3
MAX_RECURRING_OCCURRENCES = 12
MAX_RECURRING_PATTERNS = 100
RECURRING_POLICY_VERSION = "2026.1"
_DETECTION_THRESHOLD = Decimal("0.700000")
_HIGH_CONFIDENCE_THRESHOLD = Decimal("0.900000")


class RecurringPatternType(StrEnum):
    """Stable behavioral meanings assigned only from canonical evidence."""

    SALARY = "salary"
    RENT = "rent"
    EMI = "emi"
    SIP = "sip"
    INSURANCE = "insurance"
    UTILITIES = "utilities"
    SUBSCRIPTION = "subscription"
    REPEATED_MERCHANT = "repeated_merchant"


class RecurringCadence(StrEnum):
    """Reviewed interval bands supported by the first recurrence policy."""

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    IRREGULAR = "irregular"


class RecurringDecision(StrEnum):
    """Whether reviewed evidence is sufficient to claim recurrence."""

    DETECTED = "detected"
    ABSTAINED = "abstained"


class RecurringConfidenceBand(StrEnum):
    """Non-probabilistic evidence bands for recurring-pattern quality."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecurringReasonCode(StrEnum):
    """Bounded reasons safe to expose without transaction descriptions."""

    CANONICAL_CATEGORY = "canonical_category"
    REPEATED_MERCHANT = "repeated_merchant"
    REGULAR_INTERVAL = "regular_interval"
    STABLE_AMOUNT = "stable_amount"
    IRREGULAR_INTERVAL = "irregular_interval"
    VARIABLE_AMOUNT = "variable_amount"


@dataclass(frozen=True, slots=True)
class RecurringPattern:
    """One explainable recurring candidate derived from owned observations."""

    pattern_type: RecurringPatternType
    transaction_type: TransactionType
    normalized_merchant: str | None
    display_name: str | None
    classification_code: str | None
    category_name: str | None
    cadence: RecurringCadence
    decision: RecurringDecision
    confidence: Decimal
    confidence_band: RecurringConfidenceBand
    reason_codes: tuple[RecurringReasonCode, ...]
    occurrence_count: int
    first_observed_date: date
    last_observed_date: date
    median_interval_days: Decimal
    median_amount: Decimal
    minimum_amount: Decimal
    maximum_amount: Decimal
    observed_total: Decimal
    explanation: str


@dataclass(frozen=True, slots=True)
class _CadenceDefinition:
    cadence: RecurringCadence
    minimum_days: Decimal
    maximum_days: Decimal


_CADENCES = (
    _CadenceDefinition(RecurringCadence.WEEKLY, Decimal("5"), Decimal("9")),
    _CadenceDefinition(
        RecurringCadence.BIWEEKLY,
        Decimal("12"),
        Decimal("16"),
    ),
    _CadenceDefinition(
        RecurringCadence.MONTHLY,
        Decimal("25"),
        Decimal("35"),
    ),
    _CadenceDefinition(
        RecurringCadence.QUARTERLY,
        Decimal("80"),
        Decimal("100"),
    ),
)

_CATEGORY_PATTERN_TYPES = {
    ClassificationSubcategoryCode.SALARY.value: RecurringPatternType.SALARY,
    ClassificationSubcategoryCode.RENT.value: RecurringPatternType.RENT,
    ClassificationSubcategoryCode.EMI_LOAN_PAYMENT.value: (
        RecurringPatternType.EMI
    ),
    ClassificationSubcategoryCode.MUTUAL_FUND.value: RecurringPatternType.SIP,
    ClassificationSubcategoryCode.HEALTH_INSURANCE.value: (
        RecurringPatternType.INSURANCE
    ),
    ClassificationSubcategoryCode.OTHER_INSURANCE.value: (
        RecurringPatternType.INSURANCE
    ),
    ClassificationSubcategoryCode.UTILITIES.value: (
        RecurringPatternType.UTILITIES
    ),
    ClassificationSubcategoryCode.STREAMING.value: (
        RecurringPatternType.SUBSCRIPTION
    ),
}

_AMOUNT_TOLERANCES = {
    RecurringPatternType.SALARY: Decimal("0.25"),
    RecurringPatternType.UTILITIES: Decimal("0.50"),
    RecurringPatternType.REPEATED_MERCHANT: Decimal("0.20"),
}
_DEFAULT_AMOUNT_TOLERANCE = Decimal("0.15")


def detect_recurring_patterns(
    records: tuple[RecurringTransactionRecord, ...],
    *,
    minimum_occurrences: int = MIN_RECURRING_OCCURRENCES,
) -> tuple[RecurringPattern, ...]:
    """Return deterministic candidates without forcing uncertain recurrence."""
    if (
        type(minimum_occurrences) is not int
        or not MIN_RECURRING_OCCURRENCES
        <= minimum_occurrences
        <= MAX_RECURRING_OCCURRENCES
    ):
        raise ValueError(
            "minimum_occurrences must be between "
            f"{MIN_RECURRING_OCCURRENCES} and {MAX_RECURRING_OCCURRENCES}."
        )

    grouped: dict[
        tuple[str, TransactionType, str],
        list[RecurringTransactionRecord],
    ] = defaultdict(list)
    for record in records:
        key = _group_key(record)
        if key is not None:
            grouped[key].append(record)

    patterns: list[RecurringPattern] = []
    for group in grouped.values():
        observations = _consolidate_daily(tuple(group))
        if len(observations) >= minimum_occurrences:
            patterns.append(_evaluate_group(observations))
    return tuple(sorted(patterns, key=_pattern_sort_key))


def _group_key(
    record: RecurringTransactionRecord,
) -> tuple[str, TransactionType, str] | None:
    if record.normalized_merchant is not None:
        return (
            "merchant",
            record.transaction_type,
            record.normalized_merchant,
        )
    if record.classification_code is not None:
        return (
            "category",
            record.transaction_type,
            record.classification_code,
        )
    return None


def _consolidate_daily(
    records: tuple[RecurringTransactionRecord, ...],
) -> tuple[RecurringTransactionRecord, ...]:
    """Treat one merchant and calendar date as one recurrence observation."""
    by_date: dict[date, list[RecurringTransactionRecord]] = defaultdict(list)
    for record in records:
        by_date[record.transaction_date].append(record)

    observations = []
    for observed_date, daily_records in sorted(by_date.items()):
        observations.append(
            RecurringTransactionRecord(
                transaction_date=observed_date,
                transaction_type=daily_records[0].transaction_type,
                amount=sum(
                    (abs(item.amount) for item in daily_records),
                    start=Decimal("0"),
                ),
                normalized_merchant=daily_records[0].normalized_merchant,
                display_name=_mode(
                    item.display_name
                    for item in daily_records
                    if item.display_name is not None
                ),
                classification_code=_mode(
                    item.classification_code
                    for item in daily_records
                    if item.classification_code is not None
                ),
                category_name=_mode(
                    item.category_name
                    for item in daily_records
                    if item.category_name is not None
                ),
            )
        )
    return tuple(observations)


def _evaluate_group(
    records: tuple[RecurringTransactionRecord, ...],
) -> RecurringPattern:
    ordered = tuple(
        sorted(
            records,
            key=lambda item: (
                item.transaction_date,
                item.amount,
                item.normalized_merchant or "",
            ),
        )
    )
    intervals = tuple(
        Decimal((current.transaction_date - previous.transaction_date).days)
        for previous, current in zip(ordered, ordered[1:])
    )
    amounts = tuple(abs(item.amount) for item in ordered)
    median_interval = _median(intervals)
    median_amount = _median(amounts)
    cadence_definition = _cadence_for(median_interval)
    cadence = (
        cadence_definition.cadence
        if cadence_definition is not None
        else RecurringCadence.IRREGULAR
    )
    interval_matches = (
        sum(
            cadence_definition.minimum_days
            <= interval
            <= cadence_definition.maximum_days
            for interval in intervals
        )
        if cadence_definition is not None
        else 0
    )
    interval_score = _ratio(interval_matches, len(intervals))
    dominant_classification_code = _mode(
        item.classification_code
        for item in ordered
        if item.classification_code is not None
    )
    category_supported = (
        dominant_classification_code is not None
        and sum(
            item.classification_code == dominant_classification_code
            for item in ordered
        )
        * 2
        > len(ordered)
    )
    classification_code = (
        dominant_classification_code if category_supported else None
    )
    mapped_pattern_type = _CATEGORY_PATTERN_TYPES.get(classification_code)
    category_signal = (
        mapped_pattern_type is not None
        and _pattern_type_is_compatible(
            mapped_pattern_type,
            transaction_type=ordered[0].transaction_type,
        )
    )
    pattern_type = (
        mapped_pattern_type
        if category_signal
        else RecurringPatternType.REPEATED_MERCHANT
    )
    amount_tolerance = _AMOUNT_TOLERANCES.get(
        pattern_type,
        _DEFAULT_AMOUNT_TOLERANCE,
    )
    amount_matches = sum(
        _within_amount_tolerance(
            amount,
            median=median_amount,
            tolerance=amount_tolerance,
        )
        for amount in amounts
    )
    amount_score = _ratio(amount_matches, len(amounts))
    confidence = (
        interval_score * Decimal("0.65")
        + amount_score * Decimal("0.35")
    ).quantize(RATIO_QUANTUM, rounding=ROUND_HALF_EVEN)
    decision = (
        RecurringDecision.DETECTED
        if cadence is not RecurringCadence.IRREGULAR
        and confidence >= _DETECTION_THRESHOLD
        else RecurringDecision.ABSTAINED
    )
    reason_codes = _reason_codes(
        category_signal=category_signal,
        cadence=cadence,
        amount_score=amount_score,
    )
    display_name = _mode(
        item.display_name for item in ordered if item.display_name is not None
    )
    category_name = (
        _mode(
            item.category_name
            for item in ordered
            if item.category_name is not None
        )
        if category_supported
        else None
    )
    explanation = _explanation(
        decision=decision,
        cadence=cadence,
        pattern_type=pattern_type,
        occurrence_count=len(ordered),
        interval_matches=interval_matches,
        interval_count=len(intervals),
        amount_matches=amount_matches,
    )
    return RecurringPattern(
        pattern_type=pattern_type,
        transaction_type=ordered[0].transaction_type,
        normalized_merchant=ordered[0].normalized_merchant,
        display_name=display_name,
        classification_code=classification_code,
        category_name=category_name,
        cadence=cadence,
        decision=decision,
        confidence=confidence,
        confidence_band=_confidence_band(
            confidence,
            occurrence_count=len(ordered),
        ),
        reason_codes=reason_codes,
        occurrence_count=len(ordered),
        first_observed_date=ordered[0].transaction_date,
        last_observed_date=ordered[-1].transaction_date,
        median_interval_days=median_interval.quantize(Decimal("0.01")),
        median_amount=money(median_amount),
        minimum_amount=money(min(amounts)),
        maximum_amount=money(max(amounts)),
        observed_total=money(sum(amounts, start=Decimal("0"))),
        explanation=explanation,
    )


def _median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("A median requires at least one value.")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _cadence_for(interval: Decimal) -> _CadenceDefinition | None:
    return next(
        (
            definition
            for definition in _CADENCES
            if definition.minimum_days <= interval <= definition.maximum_days
        ),
        None,
    )


def _within_amount_tolerance(
    amount: Decimal,
    *,
    median: Decimal,
    tolerance: Decimal,
) -> bool:
    if median <= 0:
        return False
    return abs(amount - median) / median <= tolerance


def _pattern_type_is_compatible(
    pattern_type: RecurringPatternType,
    *,
    transaction_type: TransactionType,
) -> bool:
    if pattern_type is RecurringPatternType.SALARY:
        return transaction_type is TransactionType.INCOME
    return transaction_type is TransactionType.EXPENSE


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.000000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _mode(values: Iterable[str]) -> str | None:
    counter = Counter(values)
    if not counter:
        return None
    highest = max(counter.values())
    return min(value for value, count in counter.items() if count == highest)


def _confidence_band(
    confidence: Decimal,
    *,
    occurrence_count: int,
) -> RecurringConfidenceBand:
    if (
        confidence >= _HIGH_CONFIDENCE_THRESHOLD
        and occurrence_count >= 4
    ):
        return RecurringConfidenceBand.HIGH
    if confidence >= _DETECTION_THRESHOLD:
        return RecurringConfidenceBand.MEDIUM
    return RecurringConfidenceBand.LOW


def _reason_codes(
    *,
    category_signal: bool,
    cadence: RecurringCadence,
    amount_score: Decimal,
) -> tuple[RecurringReasonCode, ...]:
    reasons = [
        RecurringReasonCode.CANONICAL_CATEGORY
        if category_signal
        else RecurringReasonCode.REPEATED_MERCHANT,
        RecurringReasonCode.REGULAR_INTERVAL
        if cadence is not RecurringCadence.IRREGULAR
        else RecurringReasonCode.IRREGULAR_INTERVAL,
        RecurringReasonCode.STABLE_AMOUNT
        if amount_score >= Decimal("0.750000")
        else RecurringReasonCode.VARIABLE_AMOUNT,
    ]
    return tuple(reasons)


def _explanation(
    *,
    decision: RecurringDecision,
    cadence: RecurringCadence,
    pattern_type: RecurringPatternType,
    occurrence_count: int,
    interval_matches: int,
    interval_count: int,
    amount_matches: int,
) -> str:
    if decision is RecurringDecision.ABSTAINED:
        return (
            f"Observed {occurrence_count} related transactions, but timing or "
            "amount evidence was not consistent enough to mark them recurring."
        )
    label = pattern_type.value.replace("_", " ")
    return (
        f"Observed {occurrence_count} {cadence.value} {label} transactions; "
        f"{interval_matches}/{interval_count} intervals and "
        f"{amount_matches}/{occurrence_count} amounts matched reviewed tolerances."
    )


def _pattern_sort_key(
    pattern: RecurringPattern,
) -> tuple[int, Decimal, Decimal, str, str]:
    decision_order = 0 if pattern.decision is RecurringDecision.DETECTED else 1
    return (
        decision_order,
        -pattern.confidence,
        -pattern.observed_total,
        pattern.pattern_type.value,
        pattern.normalized_merchant or pattern.classification_code or "",
    )
