"""Strict immutable assumptions for Phase 11 what-if scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from falcon_api.models.enums import GoalPriority
from falcon_api.scenario_simulation.semantics import (
    MAX_GOAL_ADJUSTMENTS,
    MAX_INCOME_INTERRUPTION_PERIODS,
    MAX_ONE_TIME_EXPENSES,
    MAX_RECURRING_EXPENSE_ADJUSTMENTS,
    MAX_SCENARIO_HORIZON_MONTHS,
    MAX_SCENARIO_NAME_LENGTH,
    MAX_SCENARIOS_PER_REQUEST,
)


_MONEY_QUANTUM = Decimal("0.0001")
_MAX_MONEY = Decimal("999999999999999.9999")
_MIN_PERCENT = Decimal("-100.0000")
_MAX_PERCENT = Decimal("300.0000")
_MIN_EMERGENCY_MONTHS = Decimal("0")
_MAX_EMERGENCY_MONTHS = Decimal("24")


def _money(value: Decimal, *, allow_zero: bool = True) -> Decimal:
    resolved = Decimal(value)
    if not resolved.is_finite() or abs(resolved) > _MAX_MONEY:
        raise ValueError("Scenario money values must be finite and bounded.")
    resolved = resolved.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    if not allow_zero and resolved == 0:
        raise ValueError("Scenario money adjustments cannot be zero.")
    return resolved


def _percentage(value: Decimal) -> Decimal:
    resolved = Decimal(value)
    if not resolved.is_finite() or not _MIN_PERCENT <= resolved <= _MAX_PERCENT:
        raise ValueError("Scenario percentage adjustments must be between -100 and 300.")
    return resolved.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def _month_start(value: date, *, label: str) -> date:
    if value.day != 1:
        raise ValueError(f"Scenario {label} must be a calendar-month boundary.")
    return value


def _month_distance(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def _period_range(start: date, end: date, *, label: str) -> tuple[date, date]:
    resolved_start = _month_start(start, label=f"{label} start")
    resolved_end = _month_start(end, label=f"{label} end")
    distance = _month_distance(resolved_start, resolved_end)
    if distance < 0:
        raise ValueError(f"Scenario {label} end cannot precede its start.")
    if distance >= MAX_SCENARIO_HORIZON_MONTHS:
        raise ValueError(f"Scenario {label} cannot exceed the supported horizon.")
    return resolved_start, resolved_end


@dataclass(frozen=True, slots=True)
class OneTimeExpenseAssumption:
    """Apply one positive hypothetical expense in a single future month."""

    period_start: date
    amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "period_start",
            _month_start(self.period_start, label="one-time expense period"),
        )
        resolved = _money(self.amount, allow_zero=False)
        if resolved < 0:
            raise ValueError("One-time scenario expenses must be positive.")
        object.__setattr__(self, "amount", resolved)


@dataclass(frozen=True, slots=True)
class RecurringExpenseAdjustment:
    """Apply one bounded signed expense adjustment over a month range."""

    start_period: date
    end_period: date
    monthly_delta: Decimal

    def __post_init__(self) -> None:
        start, end = _period_range(
            self.start_period,
            self.end_period,
            label="recurring expense adjustment",
        )
        object.__setattr__(self, "start_period", start)
        object.__setattr__(self, "end_period", end)
        object.__setattr__(
            self,
            "monthly_delta",
            _money(self.monthly_delta, allow_zero=False),
        )


@dataclass(frozen=True, slots=True)
class IncomeInterruptionAssumption:
    """Retain a bounded percentage of forecast income over a month range."""

    start_period: date
    end_period: date
    retained_income_percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        start, end = _period_range(
            self.start_period,
            self.end_period,
            label="income interruption",
        )
        retained = Decimal(self.retained_income_percent)
        if not retained.is_finite() or not Decimal("0") <= retained <= Decimal("100"):
            raise ValueError("Retained income must be between 0 and 100 percent.")
        object.__setattr__(self, "start_period", start)
        object.__setattr__(self, "end_period", end)
        object.__setattr__(
            self,
            "retained_income_percent",
            retained.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN),
        )


@dataclass(frozen=True, slots=True)
class GoalScenarioAdjustment:
    """Describe comparison-only changes for one frozen Phase 10 goal."""

    goal_id: UUID
    target_amount: Decimal | None = None
    target_date: date | None = None
    priority: GoalPriority | None = None
    monthly_contribution_delta: Decimal | None = None
    pause_start: date | None = None
    pause_end: date | None = None

    def __post_init__(self) -> None:
        if self.target_amount is not None:
            amount = _money(self.target_amount, allow_zero=False)
            if amount < 0:
                raise ValueError("Scenario goal targets must be positive.")
            object.__setattr__(self, "target_amount", amount)
        if self.priority is not None:
            object.__setattr__(self, "priority", GoalPriority(self.priority))
        if self.monthly_contribution_delta is not None:
            object.__setattr__(
                self,
                "monthly_contribution_delta",
                _money(self.monthly_contribution_delta, allow_zero=False),
            )
        if (self.pause_start is None) != (self.pause_end is None):
            raise ValueError("Goal-funding pauses require both start and end periods.")
        if self.pause_start is not None and self.pause_end is not None:
            start, end = _period_range(
                self.pause_start,
                self.pause_end,
                label="goal-funding pause",
            )
            object.__setattr__(self, "pause_start", start)
            object.__setattr__(self, "pause_end", end)
        if all(
            value is None
            for value in (
                self.target_amount,
                self.target_date,
                self.priority,
                self.monthly_contribution_delta,
                self.pause_start,
            )
        ):
            raise ValueError("A goal scenario adjustment must change at least one value.")


@dataclass(frozen=True, slots=True)
class ScenarioAssumptions:
    """One named, bounded and immutable hypothetical alternative."""

    name: str
    income_change_percent: Decimal = Decimal("0")
    expense_change_percent: Decimal = Decimal("0")
    one_time_expenses: tuple[OneTimeExpenseAssumption, ...] = ()
    recurring_expense_adjustments: tuple[RecurringExpenseAdjustment, ...] = ()
    income_interruptions: tuple[IncomeInterruptionAssumption, ...] = ()
    goal_adjustments: tuple[GoalScenarioAdjustment, ...] = ()
    emergency_fund_target_months: Decimal | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if (
            not name
            or len(name) > MAX_SCENARIO_NAME_LENGTH
            or not name.isprintable()
        ):
            raise ValueError("Scenario names must be printable and between 1 and 80 characters.")
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "income_change_percent",
            _percentage(self.income_change_percent),
        )
        object.__setattr__(
            self,
            "expense_change_percent",
            _percentage(self.expense_change_percent),
        )
        _bounded_items(
            self.one_time_expenses,
            maximum=MAX_ONE_TIME_EXPENSES,
            label="one-time expenses",
        )
        _bounded_items(
            self.recurring_expense_adjustments,
            maximum=MAX_RECURRING_EXPENSE_ADJUSTMENTS,
            label="recurring expense adjustments",
        )
        _bounded_items(
            self.income_interruptions,
            maximum=MAX_INCOME_INTERRUPTION_PERIODS,
            label="income interruptions",
        )
        _bounded_items(
            self.goal_adjustments,
            maximum=MAX_GOAL_ADJUSTMENTS,
            label="goal adjustments",
        )
        goal_ids = tuple(item.goal_id for item in self.goal_adjustments)
        if len(goal_ids) != len(set(goal_ids)):
            raise ValueError("A scenario may adjust each goal at most once.")
        if self.emergency_fund_target_months is not None:
            months = Decimal(self.emergency_fund_target_months)
            if (
                not months.is_finite()
                or not _MIN_EMERGENCY_MONTHS <= months <= _MAX_EMERGENCY_MONTHS
            ):
                raise ValueError("Emergency-fund target months must be between 0 and 24.")
            object.__setattr__(
                self,
                "emergency_fund_target_months",
                months.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN),
            )
        if not self.has_override:
            raise ValueError("A user-defined scenario must include at least one override.")

    @property
    def has_override(self) -> bool:
        """Return whether this user scenario differs from server-owned cases."""
        return bool(
            self.income_change_percent
            or self.expense_change_percent
            or self.one_time_expenses
            or self.recurring_expense_adjustments
            or self.income_interruptions
            or self.goal_adjustments
            or self.emergency_fund_target_months is not None
        )


def validate_scenario_assumptions(
    scenarios: tuple[ScenarioAssumptions, ...],
) -> tuple[ScenarioAssumptions, ...]:
    """Return a bounded set of uniquely named user alternatives."""
    if not scenarios or len(scenarios) > MAX_SCENARIOS_PER_REQUEST:
        raise ValueError("A scenario request must contain between 1 and 10 alternatives.")
    names = tuple(item.name.casefold() for item in scenarios)
    if len(names) != len(set(names)):
        raise ValueError("Scenario names must be unique within one request.")
    return scenarios


def _bounded_items(items: tuple[object, ...], *, maximum: int, label: str) -> None:
    if len(items) > maximum:
        raise ValueError(f"Scenario {label} exceed the supported limit of {maximum}.")
