"""Owner-scoped persistence for immutable scenario results and selection history."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from falcon_api.analytics.types import money
from falcon_api.models.enums import (
    ScenarioSimulationEventSource,
    ScenarioSimulationEventType,
)
from falcon_api.models.scenario import (
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioEvent,
    ScenarioGoalOutcome,
    ScenarioPeriod,
    ScenarioSimulationRun,
)
from falcon_api.scenario_simulation.decision import (
    ScenarioAlternativeDecision,
    ScenarioDecisionAnalysis,
    validate_scenario_decision_analysis,
)
from falcon_api.scenario_simulation.semantics import (
    SCENARIO_MONTE_CARLO_POLICY_VERSION,
    SCENARIO_PERSISTENCE_POLICY_VERSION,
    SCENARIO_RISK_POLICY_VERSION,
    ScenarioCaseKind,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceSnapshot


MAX_SCENARIO_RUN_HISTORY = 100


class ScenarioSimulationRepository:
    """Create and read scenario history only through an authenticated owner."""

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        snapshot: ScenarioEvidenceSnapshot,
        analysis: ScenarioDecisionAnalysis,
        occurred_at: datetime,
    ) -> ScenarioSimulationRun:
        _validate_write(
            user_id=user_id,
            snapshot=snapshot,
            analysis=analysis,
            occurred_at=occurred_at,
        )
        run_id = uuid4()
        definition_ids = {
            item.path.path_id: uuid4() for item in analysis.alternatives
        }
        definitions = sorted(
            (
                _definition(
                    run_id=run_id,
                    definition_id=definition_ids[item.path.path_id],
                    user_id=user_id,
                    ordinal=_definition_ordinal(snapshot, item),
                    alternative=item,
                )
                for item in analysis.alternatives
            ),
            key=lambda item: item.ordinal,
        )
        definitions_by_path = {
            item.path_id: item for item in definitions
        }
        comparisons = [
            _comparison(
                run_id=run_id,
                user_id=user_id,
                alternative=item,
                definition_ids=definition_ids,
            )
            for item in analysis.alternatives
        ]
        for item in comparisons:
            definitions_by_path[
                next(
                    path_id
                    for path_id, identifier in definition_ids.items()
                    if identifier == item.scenario_definition_id
                )
            ].comparison = item
        periods = tuple(item.period_start for item in snapshot.periods)
        first_risk = analysis.alternatives[0].risk
        run = ScenarioSimulationRun(
            id=run_id,
            user_id=user_id,
            source_plan_id=snapshot.source_plan.run_id,
            snapshot_id=snapshot.snapshot_id,
            analysis_id=analysis.analysis_id,
            baseline_path_id=analysis.baseline_path_id,
            currency=snapshot.currency,
            cutoff_at=snapshot.cutoff_at,
            local_date=snapshot.local_date,
            timezone=snapshot.timezone,
            horizon_start=periods[0] if periods else None,
            horizon_end=periods[-1] if periods else None,
            contract_version=snapshot.contract_version,
            comparison_policy_version=analysis.comparison_policy_version,
            sensitivity_policy_version=analysis.sensitivity_policy_version,
            decision_policy_version=analysis.decision_policy_version,
            persistence_policy_version=SCENARIO_PERSISTENCE_POLICY_VERSION,
            monte_carlo_policy_version=SCENARIO_MONTE_CARLO_POLICY_VERSION,
            risk_policy_version=SCENARIO_RISK_POLICY_VERSION,
            probability_method=first_risk.probability_method,
            percentile_method=first_risk.percentile_method,
            root_seed=analysis.root_seed,
            trial_count=analysis.trial_count,
            horizon_months=len(periods),
            scenario_count=len(definitions),
            snapshot_warnings=[item.value for item in snapshot.warnings],
            reason_codes=[item.value for item in analysis.reason_codes],
            definitions=definitions,
            comparisons=comparisons,
            events=[
                ScenarioEvent(
                    user_id=user_id,
                    simulation_run_id=run_id,
                    scenario_definition_id=None,
                    event_type=ScenarioSimulationEventType.GENERATED,
                    source=ScenarioSimulationEventSource.SYSTEM,
                    occurred_at=occurred_at,
                    reason_code="scenario_run_generated",
                )
            ],
        )
        session.add(run)
        await session.flush()
        return run

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run_id: UUID,
        for_update: bool = False,
    ) -> ScenarioSimulationRun | None:
        statement = (
            select(ScenarioSimulationRun)
            .options(*_load_options())
            .where(
                ScenarioSimulationRun.user_id == user_id,
                ScenarioSimulationRun.id == run_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[ScenarioSimulationRun, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= MAX_SCENARIO_RUN_HISTORY:
            raise ValueError("Scenario history limit must be between 1 and 100.")
        rows = await session.scalars(
            select(ScenarioSimulationRun)
            .options(*_load_options())
            .where(ScenarioSimulationRun.user_id == user_id)
            .order_by(
                ScenarioSimulationRun.created_at.desc(),
                ScenarioSimulationRun.id.desc(),
            )
            .limit(limit)
        )
        return tuple(rows.all())

    async def select(
        self,
        session: AsyncSession,
        *,
        run: ScenarioSimulationRun,
        user_id: UUID,
        scenario_definition_id: UUID,
        occurred_at: datetime,
        reason_code: str = "user_selected_scenario",
    ) -> ScenarioSimulationRun:
        _validate_selection_event(
            run=run,
            user_id=user_id,
            occurred_at=occurred_at,
            reason_code=reason_code,
        )
        definition_ids = {item.id for item in run.definitions}
        if scenario_definition_id not in definition_ids:
            raise ValueError("Scenario selections require a definition from the run.")
        if run.selected_scenario_id == scenario_definition_id:
            raise ValueError("The requested scenario is already selected.")
        run.events.append(
            ScenarioEvent(
                user_id=user_id,
                simulation_run_id=run.id,
                scenario_definition_id=scenario_definition_id,
                event_type=ScenarioSimulationEventType.SELECTED,
                source=ScenarioSimulationEventSource.USER,
                occurred_at=occurred_at,
                reason_code=reason_code,
            )
        )
        await session.flush()
        return run

    async def clear_selection(
        self,
        session: AsyncSession,
        *,
        run: ScenarioSimulationRun,
        user_id: UUID,
        expected_scenario_definition_id: UUID,
        occurred_at: datetime,
        reason_code: str = "user_cleared_scenario_selection",
    ) -> ScenarioSimulationRun:
        _validate_selection_event(
            run=run,
            user_id=user_id,
            occurred_at=occurred_at,
            reason_code=reason_code,
        )
        if run.selected_scenario_id != expected_scenario_definition_id:
            raise ValueError("Scenario selection state changed before it was cleared.")
        run.events.append(
            ScenarioEvent(
                user_id=user_id,
                simulation_run_id=run.id,
                scenario_definition_id=None,
                event_type=ScenarioSimulationEventType.SELECTION_CLEARED,
                source=ScenarioSimulationEventSource.USER,
                occurred_at=occurred_at,
                reason_code=reason_code,
            )
        )
        await session.flush()
        return run


def _definition(
    *,
    run_id: UUID,
    definition_id: UUID,
    user_id: UUID,
    ordinal: int,
    alternative: ScenarioAlternativeDecision,
) -> ScenarioDefinition:
    evaluation = alternative.evaluation
    risk = alternative.risk
    empirical = {item.goal_id: item for item in risk.goals}
    evaluation_periods = {item.period_start: item for item in evaluation.periods}
    periods: list[ScenarioPeriod] = []
    for item in alternative.path.periods:
        evaluated = evaluation_periods.get(item.period_start)
        if evaluated is None or money(evaluated.available_capacity) != money(
            item.selected_capacity
        ):
            raise ValueError("Scenario periods must reconcile with the evaluation.")
        periods.append(
            ScenarioPeriod(
                user_id=user_id,
                simulation_run_id=run_id,
                scenario_definition_id=definition_id,
                period_start=item.period_start,
                source_capacity=money(item.source_protected_amount),
                income_delta=money(item.income_delta),
                expense_delta=money(item.expense_delta),
                one_time_expense=money(item.one_time_expense),
                recurring_expense_delta=money(item.recurring_expense_delta),
                debt_payment_delta=money(item.debt_payment_delta),
                raw_protected_amount=money(item.raw_protected_amount),
                raw_expected_amount=money(item.raw_expected_amount),
                raw_upside_amount=money(item.raw_upside_amount),
                selected_capacity=money(item.selected_capacity),
                allocated_amount=money(evaluated.allocated_amount),
                unallocated_amount=money(evaluated.unallocated_amount),
            )
        )
    outcomes = [
        _goal_outcome(
            run_id=run_id,
            definition_id=definition_id,
            user_id=user_id,
            deterministic=item,
            empirical=empirical.get(item.goal_id),
        )
        for item in evaluation.goals
    ]
    reason_codes = tuple(
        dict.fromkeys(
            (
                *(item.value for item in alternative.path.reason_codes),
                *(item.value for item in evaluation.reason_codes),
                *(item.value for item in risk.reason_codes),
                *(item.value for item in alternative.reason_codes),
            )
        )
    )
    return ScenarioDefinition(
        id=definition_id,
        user_id=user_id,
        simulation_run_id=run_id,
        path_id=alternative.path.path_id,
        evaluation_id=evaluation.evaluation_id,
        risk_id=risk.risk_id,
        simulation_id=risk.simulation_id,
        ordinal=ordinal,
        name=alternative.path.name,
        kind=alternative.path.kind.value,
        evaluation_status=evaluation.status.value,
        risk_status=risk.status.value,
        selected_band=alternative.path.selected_band,
        reliability=risk.reliability.value,
        assumptions=(
            _json_value(asdict(alternative.path.assumptions))
            if alternative.path.assumptions is not None
            else None
        ),
        reason_codes=list(reason_codes),
        emergency_reserve_amount=money(evaluation.emergency_reserve_amount),
        capacity_total=money(evaluation.capacity_total),
        allocated_total=money(evaluation.allocated_total),
        unallocated_total=money(evaluation.unallocated_total),
        weighted_funding_score=evaluation.weighted_funding_score,
        all_goals_completion_probability=risk.all_goals_completion_probability,
        all_deadlines_met_probability=risk.all_deadlines_met_probability,
        reserve_coverage_probability=risk.emergency_reserve_coverage_probability,
        negative_savings_probability=risk.negative_savings_probability,
        constraint_feasibility_probability=risk.constraint_feasibility_probability,
        expected_capacity=(
            money(risk.expected_capacity)
            if risk.expected_capacity is not None
            else None
        ),
        expected_total_shortfall=(
            money(risk.expected_total_shortfall)
            if risk.expected_total_shortfall is not None
            else None
        ),
        tail_expected_shortfall_90=(
            money(risk.tail_expected_shortfall_90)
            if risk.tail_expected_shortfall_90 is not None
            else None
        ),
        robustness_score=risk.robustness_score,
        periods=periods,
        outcomes=outcomes,
    )


def _definition_ordinal(
    snapshot: ScenarioEvidenceSnapshot,
    alternative: ScenarioAlternativeDecision,
) -> int:
    assumptions = alternative.path.assumptions
    if assumptions is None:
        references = {
            ScenarioCaseKind.PROTECTED: 1,
            ScenarioCaseKind.EXPECTED: 2,
            ScenarioCaseKind.UPSIDE: 3,
        }
        try:
            return references[alternative.path.kind]
        except KeyError:
            raise ValueError("Standard scenario definition kind is invalid.") from None
    try:
        return snapshot.scenarios.index(assumptions) + 4
    except ValueError:
        raise ValueError(
            "User-defined scenario assumptions are not in the trusted snapshot."
        ) from None


def _goal_outcome(
    *,
    run_id: UUID,
    definition_id: UUID,
    user_id: UUID,
    deterministic: Any,
    empirical: Any | None,
) -> ScenarioGoalOutcome:
    return ScenarioGoalOutcome(
        user_id=user_id,
        simulation_run_id=run_id,
        scenario_definition_id=definition_id,
        goal_id=deterministic.goal_id,
        rank=deterministic.rank,
        feasibility_state=deterministic.feasibility_state,
        deadline_risk=deterministic.deadline_risk,
        allocated_amount=money(deterministic.allocated_amount),
        projected_remaining_amount=money(deterministic.projected_remaining_amount),
        protected_shortfall=money(deterministic.protected_shortfall),
        expected_shortfall=money(deterministic.expected_shortfall),
        deterministic_completion_probability=deterministic.completion_probability,
        empirical_completion_probability=(
            empirical.completion_probability if empirical is not None else None
        ),
        deadline_met_probability=(
            empirical.deadline_met_probability if empirical is not None else None
        ),
        completion_count=empirical.completion_count if empirical is not None else 0,
        completion_denominator=(
            empirical.completion_denominator if empirical is not None else 0
        ),
        deadline_met_count=(
            empirical.deadline_met_count if empirical is not None else 0
        ),
        deadline_denominator=(
            empirical.deadline_denominator if empirical is not None else 0
        ),
        completion_period_p10=(
            empirical.completion_period_p10 if empirical is not None else None
        ),
        completion_period_p50=(
            empirical.completion_period_p50 if empirical is not None else None
        ),
        completion_period_p90=(
            empirical.completion_period_p90 if empirical is not None else None
        ),
        empirical_expected_shortfall=(
            money(empirical.expected_shortfall) if empirical is not None else None
        ),
        empirical_shortfall_p90=(
            money(empirical.shortfall_p90) if empirical is not None else None
        ),
        deterministic_deadline_met=deterministic.deadline_met,
    )


def _comparison(
    *,
    run_id: UUID,
    user_id: UUID,
    alternative: ScenarioAlternativeDecision,
    definition_ids: dict[str, UUID],
) -> ScenarioComparison:
    return ScenarioComparison(
        user_id=user_id,
        simulation_run_id=run_id,
        scenario_definition_id=definition_ids[alternative.path.path_id],
        baseline_definition_id=definition_ids[alternative.baseline_path_id],
        dominated_by_definition_id=(
            definition_ids[alternative.dominated_by_path_id]
            if alternative.dominated_by_path_id is not None
            else None
        ),
        comparison_hash=alternative.comparison_id,
        expected_capacity_delta=alternative.expected_capacity_delta,
        completion_probability_delta=alternative.completion_probability_delta,
        deadline_probability_delta=alternative.deadline_probability_delta,
        reserve_probability_delta=alternative.reserve_probability_delta,
        negative_savings_probability_delta=(
            alternative.negative_savings_probability_delta
        ),
        expected_shortfall_delta=alternative.expected_shortfall_delta,
        tail_shortfall_delta=alternative.tail_shortfall_delta,
        robustness_delta=alternative.robustness_delta,
        weighted_funding_delta=alternative.weighted_funding_delta,
        fully_funded_goal_delta=alternative.fully_funded_goal_delta,
        deadline_met_goal_delta=alternative.deadline_met_goal_delta,
        additional_required_contribution=(
            alternative.additional_required_contribution
        ),
        decision_score=alternative.decision_score,
        rank=alternative.rank,
        recommended=alternative.recommended,
        sensitivity_signals=[
            _json_value(asdict(item)) for item in alternative.sensitivity_signals
        ],
        reason_codes=[item.value for item in alternative.reason_codes],
    )


def _validate_write(
    *,
    user_id: UUID,
    snapshot: ScenarioEvidenceSnapshot,
    analysis: ScenarioDecisionAnalysis,
    occurred_at: datetime,
) -> None:
    if snapshot.user_id != user_id:
        raise ValueError("Scenario persistence requires the trusted owner.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("Scenario event timestamps must be timezone-aware.")
    if occurred_at < snapshot.cutoff_at:
        raise ValueError("Scenario generation cannot precede the trusted cutoff.")
    validate_scenario_decision_analysis(snapshot=snapshot, analysis=analysis)
    expected_count = len(snapshot.scenarios) + 3
    if len(analysis.alternatives) != expected_count:
        raise ValueError("Scenario persistence requires every bounded alternative.")
    if any(
        item.risk.trial_count not in {0, analysis.trial_count}
        or item.risk.seed != analysis.root_seed
        for item in analysis.alternatives
    ):
        raise ValueError("Scenario persistence requires one replay seed and trial count.")
    for alternative in analysis.alternatives:
        score = sum(
            (item.influence_score for item in alternative.sensitivity_signals),
            Decimal("0"),
        )
        if abs(score - Decimal("100")) > Decimal("0.0010"):
            raise ValueError("Scenario sensitivity scores must reconcile to 100.")


def _validate_selection_event(
    *,
    run: ScenarioSimulationRun,
    user_id: UUID,
    occurred_at: datetime,
    reason_code: str,
) -> None:
    if run.user_id != user_id:
        raise ValueError("Scenario selection history requires the trusted owner.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("Scenario event timestamps must be timezone-aware.")
    if run.events and occurred_at < run.events[-1].occurred_at:
        raise ValueError("Scenario event timestamps must be chronological.")
    if not reason_code.strip() or len(reason_code) > 64:
        raise ValueError("Scenario event reasons must be bounded and non-blank.")


def _load_options() -> tuple[Any, ...]:
    return (
        selectinload(ScenarioSimulationRun.definitions).selectinload(
            ScenarioDefinition.periods
        ),
        selectinload(ScenarioSimulationRun.definitions).selectinload(
            ScenarioDefinition.outcomes
        ),
        selectinload(ScenarioSimulationRun.definitions).selectinload(
            ScenarioDefinition.comparison
        ),
        selectinload(ScenarioSimulationRun.comparisons),
        selectinload(ScenarioSimulationRun.events),
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
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
    raise TypeError(f"Unsupported scenario persistence value: {type(value).__name__}")
