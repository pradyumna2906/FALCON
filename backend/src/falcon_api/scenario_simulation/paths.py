"""Deterministic Phase 11 scenario paths and ordered financial shocks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID

from falcon_api.analytics.types import money
from falcon_api.scenario_simulation.assumptions import ScenarioAssumptions
from falcon_api.scenario_simulation.semantics import (
    SCENARIO_PATH_POLICY_VERSION,
    ScenarioCaseKind,
    ScenarioPathStatus,
    ScenarioReasonCode,
    ScenarioSnapshotWarning,
)
from falcon_api.scenario_simulation.snapshot import (
    ScenarioEvidenceSnapshot,
    ScenarioForecastEvidence,
)


_MAX_MONEY = Decimal("999999999999999.9999")


@dataclass(frozen=True, slots=True)
class ScenarioCapacityPeriod:
    """One reconciled monthly path after applying every deterministic shock once."""

    period_start: date
    source_protected_amount: Decimal
    source_expected_amount: Decimal
    source_upside_amount: Decimal
    income_delta: Decimal
    expense_delta: Decimal
    one_time_expense: Decimal
    recurring_expense_delta: Decimal
    debt_payment_delta: Decimal
    raw_protected_amount: Decimal
    raw_expected_amount: Decimal
    raw_upside_amount: Decimal
    protected_amount: Decimal
    expected_amount: Decimal
    upside_amount: Decimal
    selected_capacity: Decimal
    adjusted_expense_baseline: Decimal | None


@dataclass(frozen=True, slots=True)
class DeterministicScenarioPath:
    """One immutable standard or user-defined monthly capacity alternative."""

    path_id: str
    snapshot_id: str
    policy_version: str
    name: str
    kind: ScenarioCaseKind
    status: ScenarioPathStatus
    selected_band: str
    assumptions: ScenarioAssumptions | None
    periods: tuple[ScenarioCapacityPeriod, ...]
    protected_total: Decimal
    expected_total: Decimal
    upside_total: Decimal
    selected_total: Decimal
    emergency_reserve_amount: Decimal
    reason_codes: tuple[ScenarioReasonCode, ...]


def build_deterministic_scenario_paths(
    snapshot: ScenarioEvidenceSnapshot,
) -> tuple[DeterministicScenarioPath, ...]:
    """Build three server-owned references followed by bounded user alternatives."""
    references = tuple(
        _reference_path(snapshot=snapshot, kind=kind)
        for kind in (
            ScenarioCaseKind.PROTECTED,
            ScenarioCaseKind.EXPECTED,
            ScenarioCaseKind.UPSIDE,
        )
    )
    user_paths = tuple(
        _user_path(snapshot=snapshot, assumptions=assumptions)
        for assumptions in snapshot.scenarios
    )
    paths = (*references, *user_paths)
    if len({item.path_id for item in paths}) != len(paths):
        raise ValueError("Deterministic scenario identifiers must be unique.")
    return paths


def _reference_path(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    kind: ScenarioCaseKind,
) -> DeterministicScenarioPath:
    base = _base_periods(snapshot)
    forecast_missing = snapshot.forecast is None
    unavailable = forecast_missing and kind is not ScenarioCaseKind.PROTECTED
    if unavailable:
        return _path(
            snapshot=snapshot,
            name=f"{kind.value.title()} reference",
            kind=kind,
            status=ScenarioPathStatus.UNAVAILABLE,
            selected_band=kind.value,
            assumptions=None,
            periods=(),
            reserve=snapshot.source_plan.emergency_reserve_amount,
            reasons=(
                _reference_reason(kind),
                ScenarioReasonCode.SOURCE_SAVINGS_FORECAST_MISSING,
            ),
        )
    periods = tuple(
        _reference_period(period=period, kind=kind)
        for period in base
    )
    reasons = [_reference_reason(kind)]
    status = ScenarioPathStatus.AVAILABLE
    if forecast_missing:
        status = ScenarioPathStatus.LIMITED
        reasons.append(ScenarioReasonCode.SOURCE_SAVINGS_FORECAST_MISSING)
    if (
        snapshot.forecast is not None
        and snapshot.forecast.uncertainty_reliability == "provisional"
    ):
        status = ScenarioPathStatus.LIMITED
        reasons.append(ScenarioReasonCode.PROVISIONAL_EVIDENCE)
    reserve = money(snapshot.source_plan.emergency_reserve_amount)
    if reserve > 0:
        reasons.append(ScenarioReasonCode.EMERGENCY_RESERVE_APPLIED)
    return _path(
        snapshot=snapshot,
        name=f"{kind.value.title()} reference",
        kind=kind,
        status=status,
        selected_band=kind.value,
        assumptions=None,
        periods=periods,
        reserve=reserve,
        reasons=tuple(reasons),
    )


def _user_path(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    assumptions: ScenarioAssumptions,
) -> DeterministicScenarioPath:
    income_required = bool(
        assumptions.income_change_percent or assumptions.income_interruptions
    )
    expense_required = bool(
        assumptions.expense_change_percent
        or assumptions.emergency_fund_target_months is not None
    )
    missing: list[ScenarioReasonCode] = []
    if income_required and snapshot.income_forecast is None:
        missing.append(ScenarioReasonCode.INCOME_FORECAST_REQUIRED)
    if expense_required and snapshot.expense_forecast is None:
        missing.append(ScenarioReasonCode.EXPENSE_FORECAST_REQUIRED)
    if missing:
        return _path(
            snapshot=snapshot,
            name=assumptions.name,
            kind=ScenarioCaseKind.USER_DEFINED,
            status=ScenarioPathStatus.UNAVAILABLE,
            selected_band=ScenarioCaseKind.PROTECTED.value,
            assumptions=assumptions,
            periods=(),
            reserve=snapshot.source_plan.emergency_reserve_amount,
            reasons=(ScenarioReasonCode.USER_ASSUMPTIONS_APPLIED, *missing),
        )

    income = _forecast_points(snapshot.income_forecast)
    expense = _forecast_points(snapshot.expense_forecast)
    clipped = False
    periods: list[ScenarioCapacityPeriod] = []
    for base in _base_periods(snapshot):
        period = base.period_start
        income_base = _expected(income.get(period))
        expense_base = _expected(expense.get(period))
        income_delta = _income_delta(
            assumptions=assumptions,
            period=period,
            baseline=income_base,
        )
        expense_delta = _percentage_delta(
            expense_base,
            assumptions.expense_change_percent,
        )
        one_time = money(
            sum(
                (
                    item.amount
                    for item in assumptions.one_time_expenses
                    if item.period_start == period
                ),
                Decimal("0"),
            )
        )
        recurring = money(
            sum(
                (
                    item.monthly_delta
                    for item in assumptions.recurring_expense_adjustments
                    if item.start_period <= period <= item.end_period
                ),
                Decimal("0"),
            )
        )
        debt = money(
            sum(
                (
                    item.monthly_delta
                    for item in assumptions.debt_payment_adjustments
                    if item.start_period <= period <= item.end_period
                ),
                Decimal("0"),
            )
        )
        total_delta = money(
            income_delta - expense_delta - one_time - recurring - debt
        )
        raw_protected = money(base.protected_amount + total_delta)
        raw_expected = money(base.expected_amount + total_delta)
        raw_upside = money(base.upside_amount + total_delta)
        if any(
            not value.is_finite() or abs(value) > _MAX_MONEY
            for value in (raw_protected, raw_expected, raw_upside)
        ):
            return _path(
                snapshot=snapshot,
                name=assumptions.name,
                kind=ScenarioCaseKind.USER_DEFINED,
                status=ScenarioPathStatus.UNAVAILABLE,
                selected_band=ScenarioCaseKind.PROTECTED.value,
                assumptions=assumptions,
                periods=(),
                reserve=snapshot.source_plan.emergency_reserve_amount,
                reasons=(
                    ScenarioReasonCode.USER_ASSUMPTIONS_APPLIED,
                    ScenarioReasonCode.CAPACITY_OUT_OF_RANGE,
                ),
            )
        if min(raw_protected, raw_expected, raw_upside) < 0:
            clipped = True
        protected = _non_negative(raw_protected)
        expected = max(protected, _non_negative(raw_expected))
        upside = max(expected, _non_negative(raw_upside))
        adjusted_expense = (
            _non_negative(expense_base + expense_delta + recurring)
            if expense_base is not None
            else None
        )
        periods.append(
            ScenarioCapacityPeriod(
                period_start=period,
                source_protected_amount=base.protected_amount,
                source_expected_amount=base.expected_amount,
                source_upside_amount=base.upside_amount,
                income_delta=income_delta,
                expense_delta=expense_delta,
                one_time_expense=one_time,
                recurring_expense_delta=recurring,
                debt_payment_delta=debt,
                raw_protected_amount=raw_protected,
                raw_expected_amount=raw_expected,
                raw_upside_amount=raw_upside,
                protected_amount=protected,
                expected_amount=expected,
                upside_amount=upside,
                selected_capacity=protected,
                adjusted_expense_baseline=adjusted_expense,
            )
        )

    reasons = [ScenarioReasonCode.USER_ASSUMPTIONS_APPLIED]
    status = ScenarioPathStatus.AVAILABLE
    if snapshot.forecast is None:
        status = ScenarioPathStatus.LIMITED
        reasons.append(ScenarioReasonCode.SOURCE_SAVINGS_FORECAST_MISSING)
    if _provisional(
        snapshot=snapshot,
        income_required=income_required,
        expense_required=expense_required,
    ):
        status = ScenarioPathStatus.LIMITED
        reasons.append(ScenarioReasonCode.PROVISIONAL_EVIDENCE)
    if clipped:
        reasons.append(ScenarioReasonCode.NEGATIVE_CAPACITY_CLIPPED)
    reserve = money(snapshot.source_plan.emergency_reserve_amount)
    if assumptions.emergency_fund_target_months is not None:
        baselines = tuple(
            item.adjusted_expense_baseline
            for item in periods
            if item.adjusted_expense_baseline is not None
        )
        if not baselines:
            return _path(
                snapshot=snapshot,
                name=assumptions.name,
                kind=ScenarioCaseKind.USER_DEFINED,
                status=ScenarioPathStatus.UNAVAILABLE,
                selected_band=ScenarioCaseKind.PROTECTED.value,
                assumptions=assumptions,
                periods=(),
                reserve=reserve,
                reasons=(
                    ScenarioReasonCode.USER_ASSUMPTIONS_APPLIED,
                    ScenarioReasonCode.EXPENSE_FORECAST_REQUIRED,
                ),
            )
        reserve = money(max(baselines) * assumptions.emergency_fund_target_months)
        if not reserve.is_finite() or reserve > _MAX_MONEY:
            return _path(
                snapshot=snapshot,
                name=assumptions.name,
                kind=ScenarioCaseKind.USER_DEFINED,
                status=ScenarioPathStatus.UNAVAILABLE,
                selected_band=ScenarioCaseKind.PROTECTED.value,
                assumptions=assumptions,
                periods=(),
                reserve=Decimal("0.0000"),
                reasons=(
                    ScenarioReasonCode.USER_ASSUMPTIONS_APPLIED,
                    ScenarioReasonCode.CAPACITY_OUT_OF_RANGE,
                ),
            )
        reasons.append(ScenarioReasonCode.EMERGENCY_RESERVE_RECALCULATED)
    if reserve > 0:
        reasons.append(ScenarioReasonCode.EMERGENCY_RESERVE_APPLIED)
    if any(
        item.monthly_contribution_delta is not None or item.pause_start is not None
        for item in assumptions.goal_adjustments
    ):
        reasons.append(ScenarioReasonCode.CONTRIBUTION_CONSTRAINT_APPLIED)
    return _path(
        snapshot=snapshot,
        name=assumptions.name,
        kind=ScenarioCaseKind.USER_DEFINED,
        status=status,
        selected_band=ScenarioCaseKind.PROTECTED.value,
        assumptions=assumptions,
        periods=tuple(periods),
        reserve=reserve,
        reasons=tuple(reasons),
    )


def _base_periods(
    snapshot: ScenarioEvidenceSnapshot,
) -> tuple[ScenarioCapacityPeriod, ...]:
    forecast = _forecast_points(snapshot.forecast)
    result: list[ScenarioCapacityPeriod] = []
    for source in snapshot.periods:
        point = forecast.get(source.period_start)
        protected = (
            _non_negative(point.lower_95)
            if point is not None
            else money(source.available_capacity)
        )
        expected = (
            max(protected, _non_negative(point.expected_value))
            if point is not None
            else protected
        )
        upside = (
            max(expected, _non_negative(point.upper_95))
            if point is not None
            else protected
        )
        result.append(
            ScenarioCapacityPeriod(
                period_start=source.period_start,
                source_protected_amount=protected,
                source_expected_amount=expected,
                source_upside_amount=upside,
                income_delta=Decimal("0.0000"),
                expense_delta=Decimal("0.0000"),
                one_time_expense=Decimal("0.0000"),
                recurring_expense_delta=Decimal("0.0000"),
                debt_payment_delta=Decimal("0.0000"),
                raw_protected_amount=protected,
                raw_expected_amount=expected,
                raw_upside_amount=upside,
                protected_amount=protected,
                expected_amount=expected,
                upside_amount=upside,
                selected_capacity=protected,
                adjusted_expense_baseline=None,
            )
        )
    return tuple(result)


def _reference_period(
    *,
    period: ScenarioCapacityPeriod,
    kind: ScenarioCaseKind,
) -> ScenarioCapacityPeriod:
    selected = {
        ScenarioCaseKind.PROTECTED: period.protected_amount,
        ScenarioCaseKind.EXPECTED: period.expected_amount,
        ScenarioCaseKind.UPSIDE: period.upside_amount,
    }[kind]
    protected = selected
    expected = max(protected, period.expected_amount)
    upside = max(expected, period.upside_amount)
    return ScenarioCapacityPeriod(
        **{
            **asdict(period),
            "protected_amount": protected,
            "expected_amount": expected,
            "upside_amount": upside,
            "selected_capacity": selected,
        }
    )


def _path(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    name: str,
    kind: ScenarioCaseKind,
    status: ScenarioPathStatus,
    selected_band: str,
    assumptions: ScenarioAssumptions | None,
    periods: tuple[ScenarioCapacityPeriod, ...],
    reserve: Decimal,
    reasons: tuple[ScenarioReasonCode, ...],
) -> DeterministicScenarioPath:
    protected_total = _total(periods, "protected_amount")
    expected_total = _total(periods, "expected_amount")
    upside_total = _total(periods, "upside_amount")
    selected_total = _total(periods, "selected_capacity")
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "policy_version": SCENARIO_PATH_POLICY_VERSION,
        "name": name,
        "kind": kind,
        "status": status,
        "selected_band": selected_band,
        "assumptions": assumptions,
        "periods": periods,
        "reserve": money(reserve),
        "reasons": reasons,
    }
    return DeterministicScenarioPath(
        path_id=_hash(payload),
        snapshot_id=snapshot.snapshot_id,
        policy_version=SCENARIO_PATH_POLICY_VERSION,
        name=name,
        kind=kind,
        status=status,
        selected_band=selected_band,
        assumptions=assumptions,
        periods=periods,
        protected_total=protected_total,
        expected_total=expected_total,
        upside_total=upside_total,
        selected_total=selected_total,
        emergency_reserve_amount=money(reserve),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _income_delta(
    *,
    assumptions: ScenarioAssumptions,
    period: date,
    baseline: Decimal | None,
) -> Decimal:
    if baseline is None:
        return Decimal("0.0000")
    adjusted = baseline + _percentage_delta(
        baseline,
        assumptions.income_change_percent,
    )
    interruption = next(
        (
            item
            for item in assumptions.income_interruptions
            if item.start_period <= period <= item.end_period
        ),
        None,
    )
    if interruption is not None:
        adjusted = money(
            adjusted * interruption.retained_income_percent / Decimal("100")
        )
    return money(adjusted - baseline)


def _percentage_delta(
    baseline: Decimal | None,
    percentage: Decimal,
) -> Decimal:
    if baseline is None:
        return Decimal("0.0000")
    return money(baseline * percentage / Decimal("100"))


def _forecast_points(
    forecast: ScenarioForecastEvidence | None,
) -> dict[date, Any]:
    return (
        {item.period_start: item for item in forecast.points}
        if forecast is not None
        else {}
    )


def _expected(point: Any | None) -> Decimal | None:
    return money(point.expected_value) if point is not None else None


def _total(
    periods: tuple[ScenarioCapacityPeriod, ...],
    field: str,
) -> Decimal:
    return money(
        sum((getattr(item, field) for item in periods), Decimal("0"))
    )


def _non_negative(value: Decimal) -> Decimal:
    return money(max(Decimal("0"), Decimal(value)))


def _reference_reason(kind: ScenarioCaseKind) -> ScenarioReasonCode:
    return {
        ScenarioCaseKind.PROTECTED: ScenarioReasonCode.PROTECTED_REFERENCE,
        ScenarioCaseKind.EXPECTED: ScenarioReasonCode.EXPECTED_REFERENCE,
        ScenarioCaseKind.UPSIDE: ScenarioReasonCode.UPSIDE_REFERENCE,
    }[kind]


def _provisional(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    income_required: bool,
    expense_required: bool,
) -> bool:
    warnings = set(snapshot.warnings)
    return (
        ScenarioSnapshotWarning.FORECAST_PROVISIONAL in warnings
        or (
            income_required
            and ScenarioSnapshotWarning.INCOME_FORECAST_PROVISIONAL in warnings
        )
        or (
            expense_required
            and ScenarioSnapshotWarning.EXPENSE_FORECAST_PROVISIONAL in warnings
        )
    )


def _hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported deterministic scenario value: {type(value).__name__}")
