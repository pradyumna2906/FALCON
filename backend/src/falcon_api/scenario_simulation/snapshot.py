"""Immutable owner-scoped evidence snapshots for Phase 11 simulations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.types import money
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.forecasting.persistence import ForecastPersistenceRepository
from falcon_api.forecasting.semantics import ForecastGranularity, ForecastTarget
from falcon_api.goal_planning.persistence import GoalPlanRepository
from falcon_api.goal_planning.semantics import trusted_local_date
from falcon_api.models.enums import GoalPlanStatus
from falcon_api.models.forecasting import ForecastRun
from falcon_api.models.goal_plan import GoalPlanRun
from falcon_api.scenario_simulation.assumptions import (
    GoalScenarioAdjustment,
    ScenarioAssumptions,
    validate_scenario_assumptions,
)
from falcon_api.scenario_simulation.repository import ScenarioForecastRepository
from falcon_api.scenario_simulation.semantics import (
    MAX_SCENARIO_HORIZON_MONTHS,
    SCENARIO_SIMULATION_CONTRACT_VERSION,
    ScenarioErrorCode,
    ScenarioSnapshotWarning,
)


@dataclass(frozen=True, slots=True)
class ScenarioForecastPointEvidence:
    period_start: date
    expected_value: Decimal
    lower_80: Decimal
    upper_80: Decimal
    lower_95: Decimal
    upper_95: Decimal


@dataclass(frozen=True, slots=True)
class ScenarioForecastEvidence:
    run_id: UUID
    contract_version: str
    quality_policy_version: str
    evaluation_policy_version: str
    feature_policy_version: str | None
    selection_policy_version: str
    uncertainty_policy_version: str
    model_code: str
    model_version: str
    uncertainty_method: str
    uncertainty_reliability: str
    data_cutoff_at: datetime
    source_last_updated_at: datetime | None
    points: tuple[ScenarioForecastPointEvidence, ...]


@dataclass(frozen=True, slots=True)
class ScenarioGoalEvidence:
    goal_id: UUID
    goal_name: str
    goal_type: str
    priority: str
    target_date: date
    rank: int
    target_amount: Decimal
    current_amount: Decimal
    starting_remaining_amount: Decimal
    allocated_amount: Decimal
    projected_remaining_amount: Decimal
    protected_shortfall: Decimal
    expected_shortfall: Decimal
    completion_probability: Decimal | None
    feasibility_state: str
    deadline_risk: str
    evidence_reliability: str
    expected_completion_period: date | None
    projected_completion_period: date | None
    deadline_met: bool


@dataclass(frozen=True, slots=True)
class ScenarioAllocationEvidence:
    goal_id: UUID
    rank: int
    amount: Decimal
    cumulative_amount: Decimal
    projected_remaining_amount: Decimal


@dataclass(frozen=True, slots=True)
class ScenarioPeriodEvidence:
    period_start: date
    available_capacity: Decimal
    allocated_amount: Decimal
    unallocated_amount: Decimal
    allocations: tuple[ScenarioAllocationEvidence, ...]


@dataclass(frozen=True, slots=True)
class ScenarioSourcePlanEvidence:
    run_id: UUID
    deterministic_plan_id: str
    planning_snapshot_id: str
    status: GoalPlanStatus
    created_at: datetime
    planning_cutoff_at: datetime
    local_date: date
    strategy: str
    overall_feasibility: str
    emergency_reserve_amount: Decimal
    available_savings: Decimal
    allocated_savings: Decimal
    unallocated_savings: Decimal
    weighted_funding_score: Decimal
    policy_versions: tuple[tuple[str, str | None], ...]
    guardrail_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioEvidenceSnapshot:
    """One private reproducible boundary between facts and hypotheses."""

    snapshot_id: str
    contract_version: str
    user_id: UUID
    cutoff_at: datetime
    local_date: date
    timezone: str
    currency: str
    source_plan: ScenarioSourcePlanEvidence
    forecast: ScenarioForecastEvidence | None
    income_forecast: ScenarioForecastEvidence | None
    expense_forecast: ScenarioForecastEvidence | None
    scenarios: tuple[ScenarioAssumptions, ...]
    goals: tuple[ScenarioGoalEvidence, ...]
    periods: tuple[ScenarioPeriodEvidence, ...]
    warnings: tuple[ScenarioSnapshotWarning, ...]


class ScenarioEvidenceService:
    """Build trusted Phase 11 inputs without mutating Phase 9 or Phase 10 data."""

    def __init__(
        self,
        *,
        plan_repository: GoalPlanRepository | None = None,
        forecast_repository: ForecastPersistenceRepository | None = None,
        scenario_forecast_repository: ScenarioForecastRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._plans = plan_repository or GoalPlanRepository()
        self._forecasts = forecast_repository or ForecastPersistenceRepository()
        self._scenario_forecasts = (
            scenario_forecast_repository or ScenarioForecastRepository()
        )
        self._clock = clock or SystemClock()

    async def build(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        source_plan_id: UUID,
        scenarios: tuple[ScenarioAssumptions, ...],
    ) -> ScenarioEvidenceSnapshot:
        try:
            definitions = validate_scenario_assumptions(scenarios)
        except ValueError:
            raise ApplicationError(
                code=ScenarioErrorCode.INVALID_ASSUMPTIONS.value,
                message="The requested scenario assumptions are invalid.",
                status_code=422,
            ) from None
        run = await self._plans.get(
            session,
            user_id=user_id,
            plan_id=source_plan_id,
        )
        if run is None:
            raise ApplicationError(
                code=ScenarioErrorCode.SOURCE_PLAN_NOT_FOUND.value,
                message="The requested source goal plan was not found.",
                status_code=404,
            )
        if run.status not in {GoalPlanStatus.GENERATED, GoalPlanStatus.APPROVED}:
            raise ApplicationError(
                code=ScenarioErrorCode.SOURCE_PLAN_UNAVAILABLE.value,
                message="The source goal plan is not available for a new simulation.",
                status_code=409,
            )
        cutoff = self._clock.now()
        try:
            _validate_source_plan(run=run, user_id=user_id, cutoff=cutoff)
            _validate_assumptions_against_plan(
                scenarios=definitions,
                run=run,
                local_date=trusted_local_date(
                    instant=cutoff,
                    timezone=run.timezone,
                ),
            )
            forecast = await self._load_forecast(
                session,
                user_id=user_id,
                run=run,
            )
            periods = _periods(run)
            source_periods = tuple(item.period_start for item in periods)
            income_forecast = await self._load_supplemental_forecast(
                session,
                user_id=user_id,
                run=run,
                target=ForecastTarget.GROSS_INCOME,
                periods=source_periods,
                required=_requires_income_forecast(definitions),
            )
            expense_forecast = await self._load_supplemental_forecast(
                session,
                user_id=user_id,
                run=run,
                target=ForecastTarget.TOTAL_EXPENSE,
                periods=source_periods,
                required=_requires_expense_forecast(definitions),
            )
            goals = _goals(run)
            warnings = _warnings(
                run=run,
                forecast=forecast,
                income_forecast=income_forecast,
                expense_forecast=expense_forecast,
                income_required=_requires_income_forecast(definitions),
                expense_required=_requires_expense_forecast(definitions),
            )
            source = _source_plan(run)
            local_date = trusted_local_date(instant=cutoff, timezone=run.timezone)
            snapshot_id = _snapshot_id(
                user_id=user_id,
                cutoff=cutoff,
                local_date=local_date,
                timezone=run.timezone,
                currency=run.currency,
                source_plan=source,
                forecast=forecast,
                income_forecast=income_forecast,
                expense_forecast=expense_forecast,
                scenarios=definitions,
                goals=goals,
                periods=periods,
                warnings=warnings,
            )
        except ValueError:
            raise ApplicationError(
                code=ScenarioErrorCode.EVIDENCE_UNAVAILABLE.value,
                message="The source evidence could not produce a safe scenario snapshot.",
                status_code=422,
            ) from None
        return ScenarioEvidenceSnapshot(
            snapshot_id=snapshot_id,
            contract_version=SCENARIO_SIMULATION_CONTRACT_VERSION,
            user_id=user_id,
            cutoff_at=cutoff,
            local_date=local_date,
            timezone=run.timezone,
            currency=run.currency,
            source_plan=source,
            forecast=forecast,
            income_forecast=income_forecast,
            expense_forecast=expense_forecast,
            scenarios=definitions,
            goals=goals,
            periods=periods,
            warnings=warnings,
        )

    async def _load_forecast(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run: GoalPlanRun,
    ) -> ScenarioForecastEvidence | None:
        if run.forecast_run_id is None:
            return None
        forecast = await self._forecasts.get(
            session,
            user_id=user_id,
            run_id=run.forecast_run_id,
        )
        if forecast is None:
            raise ValueError("The source plan forecast is unavailable.")
        _validate_forecast(run=run, forecast=forecast, user_id=user_id)
        return _forecast_evidence(forecast)

    async def _load_supplemental_forecast(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run: GoalPlanRun,
        target: ForecastTarget,
        periods: tuple[date, ...],
        required: bool,
    ) -> ScenarioForecastEvidence | None:
        if not required:
            return None
        forecast = await self._scenario_forecasts.latest_eligible(
            session,
            user_id=user_id,
            currency=run.currency,
            target=target,
            cutoff_at=run.planning_cutoff_at,
            periods=periods,
        )
        if forecast is None:
            return None
        _validate_supplemental_forecast(
            run=run,
            forecast=forecast,
            user_id=user_id,
            target=target,
        )
        return _forecast_evidence(forecast)


def _forecast_evidence(forecast: ForecastRun) -> ScenarioForecastEvidence:
    return ScenarioForecastEvidence(
        run_id=forecast.id,
        contract_version=forecast.contract_version,
        quality_policy_version=forecast.quality_policy_version,
        evaluation_policy_version=forecast.evaluation_policy_version,
        feature_policy_version=forecast.feature_policy_version,
        selection_policy_version=forecast.selection_policy_version,
        uncertainty_policy_version=forecast.uncertainty_policy_version,
        model_code=forecast.model_code,
        model_version=forecast.model_version,
        uncertainty_method=forecast.uncertainty_method,
        uncertainty_reliability=forecast.uncertainty_reliability,
        data_cutoff_at=forecast.data_cutoff_at,
        source_last_updated_at=forecast.source_last_updated_at,
        points=tuple(
            ScenarioForecastPointEvidence(
                period_start=point.period_start,
                expected_value=money(point.expected_value),
                lower_80=money(point.lower_80),
                upper_80=money(point.upper_80),
                lower_95=money(point.lower_95),
                upper_95=money(point.upper_95),
            )
            for point in forecast.points
        ),
    )


def _validate_source_plan(*, run: GoalPlanRun, user_id: UUID, cutoff: datetime) -> None:
    if run.user_id != user_id:
        raise ValueError("Scenario source plans must belong to the trusted owner.")
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Scenario cutoffs must be timezone-aware.")
    for timestamp in (run.created_at, run.planning_cutoff_at):
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Scenario source timestamps must be timezone-aware.")
        if timestamp > cutoff:
            raise ValueError("Scenario source evidence cannot exceed its cutoff.")
    if not run.events or run.events[0].status != GoalPlanStatus.GENERATED:
        raise ValueError("A source plan must begin with a generated lifecycle event.")
    event_times = tuple(item.occurred_at for item in run.events)
    if any(
        item.tzinfo is None or item.utcoffset() is None
        for item in event_times
    ):
        raise ValueError("Source plan lifecycle timestamps must be timezone-aware.")
    if event_times != tuple(sorted(event_times)):
        raise ValueError("Source plan lifecycle timestamps must be chronological.")
    if event_times[0] < run.planning_cutoff_at or event_times[-1] > cutoff:
        raise ValueError("Source plan lifecycle evidence exceeds a trusted cutoff.")
    if len(run.periods) > MAX_SCENARIO_HORIZON_MONTHS:
        raise ValueError("The source plan exceeds the scenario horizon limit.")
    periods = tuple(item.period_start for item in run.periods)
    if periods != tuple(sorted(set(periods))) or any(item.day != 1 for item in periods):
        raise ValueError("Source plan periods must be unique ordered month boundaries.")
    ranks = tuple(item.rank for item in run.outcomes)
    if ranks != tuple(range(1, len(ranks) + 1)):
        raise ValueError("Source goal ranks must be contiguous and ordered.")
    if run.goal_count != len(run.outcomes):
        raise ValueError("Source plan goal counts must match frozen outcomes.")


def _validate_forecast(
    *,
    run: GoalPlanRun,
    forecast: ForecastRun,
    user_id: UUID,
) -> None:
    if forecast.user_id != user_id or forecast.id != run.forecast_run_id:
        raise ValueError("Scenario forecasts must match the owned source plan.")
    if ForecastTarget(forecast.target) is not ForecastTarget.SAVINGS_AMOUNT:
        raise ValueError("Scenario forecasts must model savings capacity.")
    if ForecastGranularity(forecast.granularity) is not ForecastGranularity.MONTH:
        raise ValueError("Scenario forecasts must use monthly periods.")
    if forecast.currency != run.currency:
        raise ValueError("Scenario forecast and plan currencies must match.")
    _validate_forecast_shape(run=run, forecast=forecast)
    for point, period in zip(forecast.points, run.periods, strict=True):
        protected = money(max(Decimal("0"), Decimal(point.lower_95)))
        if protected != money(period.available_capacity):
            raise ValueError("Scenario forecast capacity must match the frozen source plan.")


def _validate_supplemental_forecast(
    *,
    run: GoalPlanRun,
    forecast: ForecastRun,
    user_id: UUID,
    target: ForecastTarget,
) -> None:
    if forecast.user_id != user_id:
        raise ValueError("Scenario supplemental forecasts must belong to the owner.")
    if ForecastTarget(forecast.target) is not target:
        raise ValueError("Scenario supplemental forecast targets must match.")
    if ForecastGranularity(forecast.granularity) is not ForecastGranularity.MONTH:
        raise ValueError("Scenario supplemental forecasts must use monthly periods.")
    if forecast.currency != run.currency:
        raise ValueError("Scenario supplemental forecast currencies must match.")
    _validate_forecast_shape(run=run, forecast=forecast)


def _validate_forecast_shape(*, run: GoalPlanRun, forecast: ForecastRun) -> None:
    timestamps = (forecast.data_cutoff_at, forecast.created_at)
    if forecast.source_last_updated_at is not None:
        timestamps += (forecast.source_last_updated_at,)
    if any(item.tzinfo is None or item.utcoffset() is None for item in timestamps):
        raise ValueError("Scenario forecast timestamps must be timezone-aware.")
    if any(item > run.planning_cutoff_at for item in timestamps):
        raise ValueError("Scenario forecasts cannot exceed the source plan cutoff.")
    plan_periods = tuple(item.period_start for item in run.periods)
    periods = tuple(item.period_start for item in forecast.points)
    if periods != plan_periods:
        raise ValueError("Scenario forecast periods must match the source plan horizon.")
    if plan_periods and (
        forecast.forecast_start != plan_periods[0]
        or forecast.forecast_end != plan_periods[-1]
        or forecast.horizon != len(plan_periods)
    ):
        raise ValueError("Scenario forecast metadata must match the source plan horizon.")
    if any(
        not Decimal(value).is_finite()
        for point in forecast.points
        for value in (
            point.expected_value,
            point.lower_80,
            point.upper_80,
            point.lower_95,
            point.upper_95,
        )
    ):
        raise ValueError("Scenario forecast values must be finite.")
    if any(
        not (
            Decimal(point.lower_95)
            <= Decimal(point.lower_80)
            <= Decimal(point.expected_value)
            <= Decimal(point.upper_80)
            <= Decimal(point.upper_95)
        )
        for point in forecast.points
    ):
        raise ValueError("Scenario forecast confidence bands must be nested.")


def _requires_income_forecast(
    scenarios: tuple[ScenarioAssumptions, ...],
) -> bool:
    return any(
        item.income_change_percent != 0 or item.income_interruptions
        for item in scenarios
    )


def _requires_expense_forecast(
    scenarios: tuple[ScenarioAssumptions, ...],
) -> bool:
    return any(
        item.expense_change_percent != 0
        or item.emergency_fund_target_months is not None
        for item in scenarios
    )


def _validate_assumptions_against_plan(
    *,
    scenarios: tuple[ScenarioAssumptions, ...],
    run: GoalPlanRun,
    local_date: date,
) -> None:
    goal_amounts = {item.goal_id: money(item.current_amount) for item in run.outcomes}
    period_set = {item.period_start for item in run.periods}
    for scenario in scenarios:
        dated_periods = {
            *(item.period_start for item in scenario.one_time_expenses),
            *(item.start_period for item in scenario.recurring_expense_adjustments),
            *(item.end_period for item in scenario.recurring_expense_adjustments),
            *(item.start_period for item in scenario.debt_payment_adjustments),
            *(item.end_period for item in scenario.debt_payment_adjustments),
            *(item.start_period for item in scenario.income_interruptions),
            *(item.end_period for item in scenario.income_interruptions),
            *(
                value
                for item in scenario.goal_adjustments
                for value in (item.pause_start, item.pause_end)
                if value is not None
            ),
        }
        if not dated_periods.issubset(period_set):
            raise ValueError("Scenario period overrides must stay inside the source horizon.")
        for adjustment in scenario.goal_adjustments:
            _validate_goal_adjustment(
                adjustment=adjustment,
                goal_amounts=goal_amounts,
                local_date=local_date,
            )


def _validate_goal_adjustment(
    *,
    adjustment: GoalScenarioAdjustment,
    goal_amounts: dict[UUID, Decimal],
    local_date: date,
) -> None:
    current = goal_amounts.get(adjustment.goal_id)
    if current is None:
        raise ValueError("Scenario goal adjustments must reference a source-plan goal.")
    if adjustment.target_amount is not None and adjustment.target_amount < current:
        raise ValueError("Scenario goal targets cannot be below frozen current progress.")
    if adjustment.target_date is not None and adjustment.target_date <= local_date:
        raise ValueError("Scenario goal target dates must remain in the future.")


def _goals(run: GoalPlanRun) -> tuple[ScenarioGoalEvidence, ...]:
    return tuple(
        ScenarioGoalEvidence(
            goal_id=item.goal_id,
            goal_name=item.goal_name,
            goal_type=item.goal_type,
            priority=item.priority,
            target_date=item.target_date,
            rank=item.rank,
            target_amount=money(item.target_amount),
            current_amount=money(item.current_amount),
            starting_remaining_amount=money(item.starting_remaining_amount),
            allocated_amount=money(item.allocated_amount),
            projected_remaining_amount=money(item.projected_remaining_amount),
            protected_shortfall=money(item.protected_shortfall),
            expected_shortfall=money(item.expected_shortfall),
            completion_probability=(
                Decimal(item.completion_probability)
                if item.completion_probability is not None
                else None
            ),
            feasibility_state=item.feasibility_state,
            deadline_risk=item.deadline_risk,
            evidence_reliability=item.evidence_reliability,
            expected_completion_period=item.expected_completion_period,
            projected_completion_period=item.projected_completion_period,
            deadline_met=item.deadline_met,
        )
        for item in run.outcomes
    )


def _periods(run: GoalPlanRun) -> tuple[ScenarioPeriodEvidence, ...]:
    return tuple(
        ScenarioPeriodEvidence(
            period_start=period.period_start,
            available_capacity=money(period.available_capacity),
            allocated_amount=money(period.allocated_amount),
            unallocated_amount=money(period.unallocated_amount),
            allocations=tuple(
                ScenarioAllocationEvidence(
                    goal_id=item.goal_id,
                    rank=item.rank,
                    amount=money(item.amount),
                    cumulative_amount=money(item.cumulative_amount),
                    projected_remaining_amount=money(item.projected_remaining_amount),
                )
                for item in period.allocations
            ),
        )
        for period in run.periods
    )


def _source_plan(run: GoalPlanRun) -> ScenarioSourcePlanEvidence:
    return ScenarioSourcePlanEvidence(
        run_id=run.id,
        deterministic_plan_id=run.deterministic_plan_id,
        planning_snapshot_id=run.snapshot_id,
        status=run.status,
        created_at=run.created_at,
        planning_cutoff_at=run.planning_cutoff_at,
        local_date=run.local_date,
        strategy=run.strategy,
        overall_feasibility=run.overall_feasibility,
        emergency_reserve_amount=money(run.emergency_reserve_amount),
        available_savings=money(run.available_savings),
        allocated_savings=money(run.allocated_savings),
        unallocated_savings=money(run.unallocated_savings),
        weighted_funding_score=Decimal(run.weighted_funding_score),
        policy_versions=(
            ("goal_planning_contract", run.contract_version),
            ("goal_plan", run.plan_policy_version),
            ("capacity", run.capacity_policy_version),
            ("feasibility", run.feasibility_policy_version),
            ("ranking", run.ranking_policy_version),
            ("greedy", run.greedy_policy_version),
            ("optimization", run.optimization_policy_version),
            ("guardrail", run.guardrail_policy_version),
        ),
        guardrail_reason_codes=tuple(run.guardrail_reason_codes),
    )


def _warnings(
    *,
    run: GoalPlanRun,
    forecast: ScenarioForecastEvidence | None,
    income_forecast: ScenarioForecastEvidence | None,
    expense_forecast: ScenarioForecastEvidence | None,
    income_required: bool,
    expense_required: bool,
) -> tuple[ScenarioSnapshotWarning, ...]:
    warnings: list[ScenarioSnapshotWarning] = []
    if forecast is None:
        warnings.append(ScenarioSnapshotWarning.FORECAST_UNAVAILABLE)
    elif forecast.uncertainty_reliability == "provisional":
        warnings.append(ScenarioSnapshotWarning.FORECAST_PROVISIONAL)
    if income_required and income_forecast is None:
        warnings.append(ScenarioSnapshotWarning.INCOME_FORECAST_UNAVAILABLE)
    elif (
        income_forecast is not None
        and income_forecast.uncertainty_reliability == "provisional"
    ):
        warnings.append(ScenarioSnapshotWarning.INCOME_FORECAST_PROVISIONAL)
    if expense_required and expense_forecast is None:
        warnings.append(ScenarioSnapshotWarning.EXPENSE_FORECAST_UNAVAILABLE)
    elif (
        expense_forecast is not None
        and expense_forecast.uncertainty_reliability == "provisional"
    ):
        warnings.append(ScenarioSnapshotWarning.EXPENSE_FORECAST_PROVISIONAL)
    if run.status is GoalPlanStatus.GENERATED:
        warnings.append(ScenarioSnapshotWarning.SOURCE_PLAN_GENERATED_ONLY)
    return tuple(warnings)


def _snapshot_id(**values: Any) -> str:
    payload = {
        "contract_version": SCENARIO_SIMULATION_CONTRACT_VERSION,
        **values,
    }
    encoded = json.dumps(
        _canonical(payload),
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
    raise TypeError(f"Unsupported scenario snapshot value: {type(value).__name__}")
