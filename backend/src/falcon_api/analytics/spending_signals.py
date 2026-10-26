"""Deterministic spending-leak and anomaly signal policy."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from enum import StrEnum

from falcon_api.analytics.periods import AnalyticsPeriod
from falcon_api.analytics.recurring import (
    RecurringDecision,
    RecurringPatternType,
    detect_recurring_patterns,
)
from falcon_api.analytics.semantics import RATIO_QUANTUM
from falcon_api.analytics.types import (
    RecurringTransactionRecord,
    SpendingSignalTransactionRecord,
    money,
)
from falcon_api.classification.taxonomy import ClassificationSubcategoryCode
from falcon_api.models.enums import TransactionType


SPENDING_SIGNAL_POLICY_VERSION = "2026.1"
MAX_SPENDING_SIGNALS = 100
_MIN_EXPENSE_SAMPLE = 5
_MIN_CONCENTRATION_SHARE = Decimal("0.300000")
_MIN_SPIKE_HISTORY_DAYS = 21
_SEVEN_DAYS = 7


class SpendingSignalFamily(StrEnum):
    """Separate reviewable leakage from statistical anomaly evidence."""

    POTENTIAL_LEAK = "potential_leak"
    ANOMALY = "anomaly"


class SpendingSignalType(StrEnum):
    """Stable checks included in the first spending-signal policy."""

    BANK_CHARGE_LEAKAGE = "bank_charge_leakage"
    REPEATED_SMALL_EXPENSES = "repeated_small_expenses"
    RECURRING_SUBSCRIPTION = "recurring_subscription"
    MERCHANT_CONCENTRATION = "merchant_concentration"
    CATEGORY_SPIKE = "category_spike"
    UNUSUAL_AMOUNT = "unusual_amount"
    DISCRETIONARY_SPIKE = "discretionary_spike"
    DUPLICATE_LIKE_EXPENSE = "duplicate_like_expense"


class SpendingSignalSeverity(StrEnum):
    """Impact bands relative to selected-period total expense."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SpendingSignalEvaluationStatus(StrEnum):
    """Whether a check ran, found evidence, or lacked a safe baseline."""

    DETECTED = "detected"
    NO_SIGNAL = "no_signal"
    INSUFFICIENT_DATA = "insufficient_data"


class SpendingSignalReasonCode(StrEnum):
    """Bounded privacy-safe reasons for a detected signal."""

    CANONICAL_BANK_CHARGE = "canonical_bank_charge"
    REPEATED_FREQUENCY = "repeated_frequency"
    RELATIVELY_SMALL_AMOUNT = "relatively_small_amount"
    CANONICAL_SUBSCRIPTION = "canonical_subscription"
    REGULAR_RECURRENCE = "regular_recurrence"
    HIGH_MERCHANT_SHARE = "high_merchant_share"
    ABOVE_ROBUST_BASELINE = "above_robust_baseline"
    DISCRETIONARY_CATEGORY = "discretionary_category"
    ROBUST_AMOUNT_OUTLIER = "robust_amount_outlier"
    SAME_DAY_MERCHANT_AMOUNT = "same_day_merchant_amount"


@dataclass(frozen=True, slots=True)
class SpendingSignal:
    """One explainable, non-prescriptive spending observation."""

    signal_type: SpendingSignalType
    family: SpendingSignalFamily
    severity: SpendingSignalSeverity
    evidence_score: Decimal
    reason_codes: tuple[SpendingSignalReasonCode, ...]
    observed_amount: Decimal
    baseline_amount: Decimal | None
    excess_amount: Decimal | None
    share_of_total_expense: Decimal | None
    occurrence_count: int
    first_observed_date: date
    last_observed_date: date
    normalized_merchant: str | None
    display_name: str | None
    classification_code: str | None
    category_name: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class SpendingSignalEvaluation:
    """Evaluation state for one policy check, including no-signal outcomes."""

    signal_type: SpendingSignalType
    status: SpendingSignalEvaluationStatus
    source_observation_count: int
    explanation: str


@dataclass(frozen=True, slots=True)
class SpendingSignalAnalysis:
    """Complete deterministic policy result before public response limiting."""

    evaluations: tuple[SpendingSignalEvaluation, ...]
    signals: tuple[SpendingSignal, ...]


_DISCRETIONARY_CODES = {
    ClassificationSubcategoryCode.RESTAURANTS.value,
    ClassificationSubcategoryCode.FOOD_DELIVERY.value,
    ClassificationSubcategoryCode.TAXI_RIDE_SHARE.value,
    ClassificationSubcategoryCode.CLOTHING.value,
    ClassificationSubcategoryCode.ELECTRONICS.value,
    ClassificationSubcategoryCode.GENERAL_SHOPPING.value,
    ClassificationSubcategoryCode.STREAMING.value,
    ClassificationSubcategoryCode.MOVIES_EVENTS.value,
    ClassificationSubcategoryCode.GAMING.value,
    ClassificationSubcategoryCode.HOBBIES.value,
}


def detect_spending_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    *,
    period: AnalyticsPeriod,
    total_expense: Decimal,
) -> SpendingSignalAnalysis:
    """Evaluate every policy check without forcing a signal from weak data."""
    normalized_total = money(total_expense)
    if normalized_total < 0:
        raise ValueError("total_expense cannot be negative.")
    ordered = tuple(
        sorted(
            records,
            key=lambda item: (
                item.transaction_date,
                item.amount,
                item.normalized_merchant or "",
                item.classification_code or "",
            ),
        )
    )
    if any(
        record.amount <= 0
        or not period.date_from <= record.transaction_date <= period.date_to
        for record in ordered
    ):
        raise ValueError(
            "Spending-signal records must be positive and inside the period."
        )

    checks = (
        _bank_charge_signals(ordered, normalized_total),
        _repeated_small_signals(ordered, normalized_total),
        _subscription_signals(ordered, normalized_total),
        _merchant_concentration_signals(ordered, normalized_total),
        _category_spike_signals(ordered, period, normalized_total),
        _unusual_amount_signals(ordered, normalized_total),
        _discretionary_spike_signals(ordered, period, normalized_total),
        _duplicate_like_signals(ordered, normalized_total),
    )
    signals = tuple(
        sorted(
            (signal for _, found in checks for signal in found),
            key=_signal_sort_key,
        )
    )
    return SpendingSignalAnalysis(
        evaluations=tuple(evaluation for evaluation, _ in checks),
        signals=signals,
    )


def _bank_charge_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    charges = tuple(
        item
        for item in records
        if item.classification_code == ClassificationSubcategoryCode.BANK_CHARGES.value
    )
    if not records:
        return _insufficient(
            SpendingSignalType.BANK_CHARGE_LEAKAGE,
            0,
            "No posted expenses were available to evaluate bank charges.",
        )
    if len(charges) < 2:
        return _no_signal(
            SpendingSignalType.BANK_CHARGE_LEAKAGE,
            len(charges),
            "Fewer than two canonical bank-charge expenses were observed.",
        )
    observed = _sum_amounts(charges)
    signal = _signal(
        signal_type=SpendingSignalType.BANK_CHARGE_LEAKAGE,
        family=SpendingSignalFamily.POTENTIAL_LEAK,
        evidence_score=_ratio(min(len(charges), 4), 4),
        reason_codes=(
            SpendingSignalReasonCode.CANONICAL_BANK_CHARGE,
            SpendingSignalReasonCode.REPEATED_FREQUENCY,
        ),
        observed_amount=observed,
        baseline_amount=None,
        excess_amount=None,
        total_expense=total_expense,
        records=charges,
        explanation=(
            f"Observed {len(charges)} canonical bank-charge expenses; this is "
            "a review signal, not a claim that the charges are avoidable."
        ),
    )
    return _detected(signal.signal_type, len(charges), (signal,))


def _repeated_small_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    signal_type = SpendingSignalType.REPEATED_SMALL_EXPENSES
    if len(records) < _MIN_EXPENSE_SAMPLE:
        return _insufficient(
            signal_type,
            len(records),
            "At least five expenses are required for a personal small-payment baseline.",
        )
    median_amount = _median(tuple(item.amount for item in records))
    small_threshold = money(median_amount * Decimal("0.50"))
    grouped = _group_records(item for item in records if item.amount <= small_threshold)
    signals = []
    for group in grouped.values():
        if len(group) < 5:
            continue
        observed = _sum_amounts(group)
        signals.append(
            _signal(
                signal_type=signal_type,
                family=SpendingSignalFamily.POTENTIAL_LEAK,
                evidence_score=_ratio(min(len(group), 10), 10),
                reason_codes=(
                    SpendingSignalReasonCode.REPEATED_FREQUENCY,
                    SpendingSignalReasonCode.RELATIVELY_SMALL_AMOUNT,
                ),
                observed_amount=observed,
                baseline_amount=small_threshold,
                excess_amount=None,
                total_expense=total_expense,
                records=tuple(group),
                explanation=(
                    f"Observed {len(group)} payments at or below half the "
                    "selected-period median expense."
                ),
            )
        )
    if not signals:
        return _no_signal(
            signal_type,
            len(records),
            "No merchant or category had five repeated relatively small payments.",
        )
    return _detected(signal_type, len(records), tuple(signals))


def _subscription_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    signal_type = SpendingSignalType.RECURRING_SUBSCRIPTION
    subscriptions = tuple(
        item
        for item in records
        if item.classification_code == ClassificationSubcategoryCode.STREAMING.value
    )
    if len(subscriptions) < 3:
        return _insufficient(
            signal_type,
            len(subscriptions),
            "At least three canonical subscription observations are required.",
        )
    recurring_records = tuple(
        RecurringTransactionRecord(
            transaction_date=item.transaction_date,
            transaction_type=TransactionType.EXPENSE,
            amount=item.amount,
            normalized_merchant=item.normalized_merchant,
            display_name=item.display_name,
            classification_code=item.classification_code,
            category_name=item.category_name,
        )
        for item in subscriptions
    )
    patterns = detect_recurring_patterns(recurring_records)
    signals = []
    for pattern in patterns:
        if (
            pattern.pattern_type is not RecurringPatternType.SUBSCRIPTION
            or pattern.decision is not RecurringDecision.DETECTED
        ):
            continue
        matching = tuple(
            item
            for item in subscriptions
            if item.normalized_merchant == pattern.normalized_merchant
        )
        signals.append(
            _signal(
                signal_type=signal_type,
                family=SpendingSignalFamily.POTENTIAL_LEAK,
                evidence_score=pattern.confidence,
                reason_codes=(
                    SpendingSignalReasonCode.CANONICAL_SUBSCRIPTION,
                    SpendingSignalReasonCode.REGULAR_RECURRENCE,
                ),
                observed_amount=pattern.observed_total,
                baseline_amount=pattern.median_amount,
                excess_amount=None,
                total_expense=total_expense,
                records=matching,
                explanation=(
                    "Observed a regular canonical subscription pattern; it may "
                    "be reviewed, but is not assumed to be unwanted."
                ),
            )
        )
    if not signals:
        return _no_signal(
            signal_type,
            len(subscriptions),
            "Canonical subscription observations did not form a regular pattern.",
        )
    return _detected(signal_type, len(subscriptions), tuple(signals))


def _merchant_concentration_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    signal_type = SpendingSignalType.MERCHANT_CONCENTRATION
    merchant_records = tuple(
        item for item in records if item.normalized_merchant is not None
    )
    if len(records) < _MIN_EXPENSE_SAMPLE or total_expense <= 0:
        return _insufficient(
            signal_type,
            len(merchant_records),
            "At least five expenses and a positive total are required.",
        )
    grouped: dict[str, list[SpendingSignalTransactionRecord]] = defaultdict(list)
    for item in merchant_records:
        grouped[item.normalized_merchant or ""].append(item)
    signals = []
    for group in grouped.values():
        observed = _sum_amounts(group)
        share = _ratio_decimal(observed, total_expense)
        if len(group) < 3 or share < _MIN_CONCENTRATION_SHARE:
            continue
        signals.append(
            _signal(
                signal_type=signal_type,
                family=SpendingSignalFamily.ANOMALY,
                evidence_score=min(
                    Decimal("1.000000"),
                    (share / Decimal("0.50")).quantize(RATIO_QUANTUM),
                ),
                reason_codes=(
                    SpendingSignalReasonCode.HIGH_MERCHANT_SHARE,
                    SpendingSignalReasonCode.REPEATED_FREQUENCY,
                ),
                observed_amount=observed,
                baseline_amount=money(total_expense * _MIN_CONCENTRATION_SHARE),
                excess_amount=money(
                    observed - total_expense * _MIN_CONCENTRATION_SHARE
                ),
                total_expense=total_expense,
                records=tuple(group),
                explanation=(
                    f"One merchant represents {share * 100:.2f}% of selected-period "
                    "expense across at least three payments."
                ),
            )
        )
    if not signals:
        return _no_signal(
            signal_type,
            len(merchant_records),
            "No merchant reached the reviewed 30% concentration threshold.",
        )
    return _detected(signal_type, len(merchant_records), tuple(signals))


def _category_spike_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    period: AnalyticsPeriod,
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    signal_type = SpendingSignalType.CATEGORY_SPIKE
    categorized = tuple(
        item for item in records if item.classification_code is not None
    )
    if period.day_count < _MIN_SPIKE_HISTORY_DAYS + _SEVEN_DAYS:
        return _insufficient(
            signal_type,
            len(categorized),
            "At least 28 selected days are required for three baseline weeks.",
        )
    groups: dict[str, list[SpendingSignalTransactionRecord]] = defaultdict(list)
    for item in categorized:
        groups[item.classification_code or ""].append(item)
    signals = []
    for group in groups.values():
        signal = _weekly_spike(
            signal_type=signal_type,
            records=tuple(group),
            period=period,
            total_expense=total_expense,
            reason_codes=(SpendingSignalReasonCode.ABOVE_ROBUST_BASELINE,),
            explanation_label="category",
        )
        if signal is not None:
            signals.append(signal)
    if not signals:
        status = (
            SpendingSignalEvaluationStatus.INSUFFICIENT_DATA
            if not categorized
            else SpendingSignalEvaluationStatus.NO_SIGNAL
        )
        return (
            _evaluation(
                signal_type,
                status,
                len(categorized),
                "No category exceeded its robust three-week spending baseline."
                if categorized
                else "Canonical category evidence is unavailable.",
            ),
            (),
        )
    return _detected(signal_type, len(categorized), tuple(signals))


def _unusual_amount_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    signal_type = SpendingSignalType.UNUSUAL_AMOUNT
    grouped = _group_records(records)
    eligible_groups = tuple(
        tuple(group) for group in grouped.values() if len(group) >= 5
    )
    if not eligible_groups:
        return _insufficient(
            signal_type,
            len(records),
            "A merchant or category needs five observations for a robust baseline.",
        )
    signals = []
    for group in eligible_groups:
        amounts = tuple(item.amount for item in group)
        median_amount = _median(amounts)
        mad = _median(tuple(abs(value - median_amount) for value in amounts))
        threshold = (
            max(
                median_amount * Decimal("1.50"),
                median_amount + Decimal("3") * mad,
            )
            if mad > 0
            else median_amount * Decimal("2")
        )
        unusual = tuple(item for item in group if item.amount > threshold)
        if not unusual:
            continue
        observed = _sum_amounts(unusual)
        baseline_total = money(median_amount * len(unusual))
        excess = money(observed - baseline_total)
        signals.append(
            _signal(
                signal_type=signal_type,
                family=SpendingSignalFamily.ANOMALY,
                evidence_score=min(
                    Decimal("1.000000"),
                    _ratio_decimal(observed, max(baseline_total, Decimal("0.0001")))
                    / Decimal("3"),
                ),
                reason_codes=(
                    SpendingSignalReasonCode.ROBUST_AMOUNT_OUTLIER,
                    SpendingSignalReasonCode.ABOVE_ROBUST_BASELINE,
                ),
                observed_amount=observed,
                baseline_amount=median_amount,
                excess_amount=excess,
                total_expense=total_expense,
                records=unusual,
                explanation=(
                    "Observed amount exceeded both the personal median multiple "
                    "and median-absolute-deviation threshold."
                ),
            )
        )
    if not signals:
        return _no_signal(
            signal_type,
            sum(len(group) for group in eligible_groups),
            "No amount exceeded its merchant or category robust baseline.",
        )
    return _detected(
        signal_type,
        sum(len(group) for group in eligible_groups),
        tuple(signals),
    )


def _discretionary_spike_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    period: AnalyticsPeriod,
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    signal_type = SpendingSignalType.DISCRETIONARY_SPIKE
    discretionary = tuple(
        item for item in records if item.classification_code in _DISCRETIONARY_CODES
    )
    if period.day_count < _MIN_SPIKE_HISTORY_DAYS + _SEVEN_DAYS:
        return _insufficient(
            signal_type,
            len(discretionary),
            "At least 28 selected days are required for three baseline weeks.",
        )
    if not discretionary:
        return _insufficient(
            signal_type,
            0,
            "Canonical discretionary-category evidence is unavailable.",
        )
    signal = _weekly_spike(
        signal_type=signal_type,
        records=discretionary,
        period=period,
        total_expense=total_expense,
        reason_codes=(
            SpendingSignalReasonCode.DISCRETIONARY_CATEGORY,
            SpendingSignalReasonCode.ABOVE_ROBUST_BASELINE,
        ),
        explanation_label="discretionary spending",
    )
    if signal is None:
        return _no_signal(
            signal_type,
            len(discretionary),
            "Recent discretionary spending did not exceed its robust baseline.",
        )
    return _detected(signal_type, len(discretionary), (signal,))


def _duplicate_like_signals(
    records: tuple[SpendingSignalTransactionRecord, ...],
    total_expense: Decimal,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    signal_type = SpendingSignalType.DUPLICATE_LIKE_EXPENSE
    comparable = tuple(item for item in records if _record_key(item) is not None)
    if len(comparable) < 2:
        return _insufficient(
            signal_type,
            len(comparable),
            "At least two merchant- or category-attributed expenses are required.",
        )
    grouped: dict[
        tuple[date, str, Decimal],
        list[SpendingSignalTransactionRecord],
    ] = defaultdict(list)
    for item in comparable:
        grouped[(item.transaction_date, _record_key(item) or "", item.amount)].append(
            item
        )
    signals = []
    for group in grouped.values():
        if len(group) < 2:
            continue
        observed = _sum_amounts(group)
        excess = money(group[0].amount * (len(group) - 1))
        signals.append(
            _signal(
                signal_type=signal_type,
                family=SpendingSignalFamily.POTENTIAL_LEAK,
                evidence_score=_ratio(len(group) - 1, len(group)),
                reason_codes=(SpendingSignalReasonCode.SAME_DAY_MERCHANT_AMOUNT,),
                observed_amount=observed,
                baseline_amount=group[0].amount,
                excess_amount=excess,
                total_expense=total_expense,
                records=tuple(group),
                explanation=(
                    f"Observed {len(group)} same-day payments with the same "
                    "merchant/category key and exact amount; manual review is needed."
                ),
            )
        )
    if not signals:
        return _no_signal(
            signal_type,
            len(comparable),
            "No same-day exact merchant/category amount duplicates were observed.",
        )
    return _detected(signal_type, len(comparable), tuple(signals))


def _weekly_spike(
    *,
    signal_type: SpendingSignalType,
    records: tuple[SpendingSignalTransactionRecord, ...],
    period: AnalyticsPeriod,
    total_expense: Decimal,
    reason_codes: tuple[SpendingSignalReasonCode, ...],
    explanation_label: str,
) -> SpendingSignal | None:
    current_from = period.date_to - timedelta(days=_SEVEN_DAYS - 1)
    current = tuple(item for item in records if item.transaction_date >= current_from)
    baseline_totals = []
    for offset in range(1, 4):
        bucket_to = current_from - timedelta(days=1 + (offset - 1) * _SEVEN_DAYS)
        bucket_from = bucket_to - timedelta(days=_SEVEN_DAYS - 1)
        baseline_totals.append(
            _sum_amounts(
                item
                for item in records
                if bucket_from <= item.transaction_date <= bucket_to
            )
        )
    if not current or sum(baseline_totals, start=Decimal("0")) <= 0:
        return None
    baseline = _median(tuple(baseline_totals))
    mad = _median(tuple(abs(value - baseline) for value in baseline_totals))
    threshold = max(
        baseline * Decimal("1.50"),
        baseline + Decimal("3") * mad,
    )
    observed = _sum_amounts(current)
    if observed <= threshold:
        return None
    excess = money(observed - baseline)
    return _signal(
        signal_type=signal_type,
        family=SpendingSignalFamily.ANOMALY,
        evidence_score=min(
            Decimal("1.000000"),
            _ratio_decimal(excess, max(observed, Decimal("0.0001"))),
        ),
        reason_codes=reason_codes,
        observed_amount=observed,
        baseline_amount=baseline,
        excess_amount=excess,
        total_expense=total_expense,
        records=current,
        explanation=(
            f"Latest seven-day {explanation_label} exceeded the median of the "
            "three preceding seven-day windows and its robust deviation threshold."
        ),
    )


def _signal(
    *,
    signal_type: SpendingSignalType,
    family: SpendingSignalFamily,
    evidence_score: Decimal,
    reason_codes: tuple[SpendingSignalReasonCode, ...],
    observed_amount: Decimal,
    baseline_amount: Decimal | None,
    excess_amount: Decimal | None,
    total_expense: Decimal,
    records: tuple[SpendingSignalTransactionRecord, ...],
    explanation: str,
) -> SpendingSignal:
    share = (
        _ratio_decimal(observed_amount, total_expense) if total_expense > 0 else None
    )
    return SpendingSignal(
        signal_type=signal_type,
        family=family,
        severity=_severity(share),
        evidence_score=evidence_score.quantize(
            RATIO_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        ),
        reason_codes=reason_codes,
        observed_amount=money(observed_amount),
        baseline_amount=(
            money(baseline_amount) if baseline_amount is not None else None
        ),
        excess_amount=(money(excess_amount) if excess_amount is not None else None),
        share_of_total_expense=share,
        occurrence_count=len(records),
        first_observed_date=min(item.transaction_date for item in records),
        last_observed_date=max(item.transaction_date for item in records),
        normalized_merchant=_common_value(item.normalized_merchant for item in records),
        display_name=_common_value(item.display_name for item in records),
        classification_code=_common_value(item.classification_code for item in records),
        category_name=_common_value(item.category_name for item in records),
        explanation=explanation,
    )


def _group_records(
    records: Iterable[SpendingSignalTransactionRecord],
) -> dict[str, list[SpendingSignalTransactionRecord]]:
    grouped: dict[str, list[SpendingSignalTransactionRecord]] = defaultdict(list)
    for item in records:
        key = _record_key(item)
        if key is not None:
            grouped[key].append(item)
    return grouped


def _record_key(item: SpendingSignalTransactionRecord) -> str | None:
    if item.normalized_merchant is not None:
        return f"merchant:{item.normalized_merchant}"
    if item.classification_code is not None:
        return f"category:{item.classification_code}"
    return None


def _sum_amounts(
    records: Iterable[SpendingSignalTransactionRecord],
) -> Decimal:
    return money(sum((item.amount for item in records), start=Decimal("0")))


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = tuple(sorted(values))
    if not ordered:
        return Decimal("0")
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _ratio(numerator: int, denominator: int) -> Decimal:
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _ratio_decimal(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(
        RATIO_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _severity(share: Decimal | None) -> SpendingSignalSeverity:
    if share is not None and share >= Decimal("0.200000"):
        return SpendingSignalSeverity.HIGH
    if share is not None and share >= Decimal("0.100000"):
        return SpendingSignalSeverity.MEDIUM
    return SpendingSignalSeverity.LOW


def _common_value(values: Iterable[str | None]) -> str | None:
    observed = {value for value in values if value is not None}
    return next(iter(observed)) if len(observed) == 1 else None


def _evaluation(
    signal_type: SpendingSignalType,
    status: SpendingSignalEvaluationStatus,
    count: int,
    explanation: str,
) -> SpendingSignalEvaluation:
    return SpendingSignalEvaluation(
        signal_type=signal_type,
        status=status,
        source_observation_count=count,
        explanation=explanation,
    )


def _detected(
    signal_type: SpendingSignalType,
    count: int,
    signals: tuple[SpendingSignal, ...],
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    return (
        _evaluation(
            signal_type,
            SpendingSignalEvaluationStatus.DETECTED,
            count,
            f"Detected {len(signals)} bounded {signal_type.value} signal(s).",
        ),
        signals,
    )


def _no_signal(
    signal_type: SpendingSignalType,
    count: int,
    explanation: str,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    return (
        _evaluation(
            signal_type,
            SpendingSignalEvaluationStatus.NO_SIGNAL,
            count,
            explanation,
        ),
        (),
    )


def _insufficient(
    signal_type: SpendingSignalType,
    count: int,
    explanation: str,
) -> tuple[SpendingSignalEvaluation, tuple[SpendingSignal, ...]]:
    return (
        _evaluation(
            signal_type,
            SpendingSignalEvaluationStatus.INSUFFICIENT_DATA,
            count,
            explanation,
        ),
        (),
    )


def _signal_sort_key(signal: SpendingSignal) -> tuple[int, Decimal, str, date]:
    severity_order = {
        SpendingSignalSeverity.HIGH: 0,
        SpendingSignalSeverity.MEDIUM: 1,
        SpendingSignalSeverity.LOW: 2,
    }
    return (
        severity_order[signal.severity],
        -signal.observed_amount,
        signal.signal_type.value,
        signal.first_observed_date,
    )
