"""Transactional orchestration for persistent Phase 11 simulations."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from time import monotonic
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning.optimizer import LinearProgramSolver
from falcon_api.models.enums import GoalPriority
from falcon_api.models.scenario import ScenarioDefinition, ScenarioSimulationRun
from falcon_api.scenario_simulation.assumptions import (
    DebtPaymentAdjustment,
    GoalScenarioAdjustment,
    IncomeInterruptionAssumption,
    OneTimeExpenseAssumption,
    RecurringExpenseAdjustment,
    ScenarioAssumptions,
    validate_scenario_assumptions,
)
from falcon_api.scenario_simulation.decision import (
    ScenarioDecisionAnalysis,
    analyze_scenario_decisions,
)
from falcon_api.scenario_simulation.monitoring import (
    ScenarioFailureReason,
    ScenarioOperation,
    ScenarioSimulationMonitor,
)
from falcon_api.scenario_simulation.monte_carlo import MonteCarloConfig
from falcon_api.scenario_simulation.persistence import (
    ScenarioSimulationRepository,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceService


MAX_CONCURRENT_SCENARIO_SIMULATIONS = 2
SCENARIO_ACQUIRE_TIMEOUT_SECONDS = 0.25
MAX_SIMULATIONS_PER_OWNER_WINDOW = 5
SCENARIO_RATE_WINDOW_SECONDS = 60.0
DecisionAnalyzer = Callable[..., ScenarioDecisionAnalysis]


@dataclass(frozen=True, slots=True)
class ScenarioSimulationCommand:
    """Trusted simulation inputs accepted after public-schema validation."""

    source_plan_id: UUID
    scenarios: tuple[ScenarioAssumptions, ...]


@dataclass(frozen=True, slots=True)
class ScenarioSelectionCommand:
    """Compare-and-set selection input preventing stale client decisions."""

    scenario_definition_id: UUID | None
    expected_selected_scenario_id: UUID | None


class ScenarioExecutionBusyError(RuntimeError):
    """Signal that bounded process-local simulation capacity is exhausted."""


class ScenarioRateLimitError(RuntimeError):
    """Signal that an owner exceeded the bounded simulation request rate."""


class ScenarioExecutionGuard:
    """Bound concurrent CPU-heavy simulations without an unbounded wait queue."""

    def __init__(
        self,
        *,
        maximum: int = MAX_CONCURRENT_SCENARIO_SIMULATIONS,
        acquire_timeout_seconds: float = SCENARIO_ACQUIRE_TIMEOUT_SECONDS,
        owner_rate_limit: int = MAX_SIMULATIONS_PER_OWNER_WINDOW,
        rate_window_seconds: float = SCENARIO_RATE_WINDOW_SECONDS,
        timer: Callable[[], float] = monotonic,
    ) -> None:
        if type(maximum) is not int or maximum < 1:
            raise ValueError("Scenario concurrency must be a positive integer.")
        if acquire_timeout_seconds <= 0:
            raise ValueError("Scenario capacity timeout must be positive.")
        if type(owner_rate_limit) is not int or owner_rate_limit < 1:
            raise ValueError("Scenario owner rate limit must be positive.")
        if rate_window_seconds <= 0:
            raise ValueError("Scenario rate window must be positive.")
        self._semaphore = asyncio.BoundedSemaphore(maximum)
        self._timeout = acquire_timeout_seconds
        self._owner_rate_limit = owner_rate_limit
        self._rate_window_seconds = rate_window_seconds
        self._timer = timer
        self._attempts: dict[UUID, deque[float]] = {}
        self._rate_lock = asyncio.Lock()

    @asynccontextmanager
    async def slot(self, *, user_id: UUID) -> AsyncIterator[None]:
        await self._reserve(user_id)
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise ScenarioExecutionBusyError from exc
        try:
            yield
        finally:
            self._semaphore.release()

    async def _reserve(self, user_id: UUID) -> None:
        now = self._timer()
        threshold = now - self._rate_window_seconds
        async with self._rate_lock:
            for owner_id, attempts in tuple(self._attempts.items()):
                while attempts and attempts[0] <= threshold:
                    attempts.popleft()
                if not attempts:
                    del self._attempts[owner_id]
            attempts = self._attempts.setdefault(user_id, deque())
            if len(attempts) >= self._owner_rate_limit:
                raise ScenarioRateLimitError
            attempts.append(now)


class ScenarioSimulationService:
    """Freeze evidence, analyze alternatives, persist, and manage selections."""

    def __init__(
        self,
        *,
        evidence_service: ScenarioEvidenceService | None = None,
        repository: ScenarioSimulationRepository | None = None,
        solver: LinearProgramSolver | None = None,
        analyzer: DecisionAnalyzer = analyze_scenario_decisions,
        monitor: ScenarioSimulationMonitor | None = None,
        execution_guard: ScenarioExecutionGuard | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._evidence = evidence_service or ScenarioEvidenceService(
            clock=self._clock
        )
        self._repository = repository or ScenarioSimulationRepository()
        self._solver = solver
        self._analyzer = analyzer
        self._monitor = monitor or ScenarioSimulationMonitor()
        self._execution_guard = execution_guard or ScenarioExecutionGuard()

    async def simulate(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        command: ScenarioSimulationCommand,
    ) -> ScenarioSimulationRun:
        return await self._execute(
            session,
            user_id=user_id,
            command=command,
            operation=ScenarioOperation.SIMULATE,
            config=None,
        )

    async def regenerate(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run_id: UUID,
    ) -> ScenarioSimulationRun:
        previous = await self._require_run(
            session,
            user_id=user_id,
            run_id=run_id,
        )
        try:
            scenarios = _stored_scenarios(previous.definitions)
        except (TypeError, ValueError):
            raise _unavailable_error() from None
        return await self._execute(
            session,
            user_id=user_id,
            command=ScenarioSimulationCommand(
                source_plan_id=previous.source_plan_id,
                scenarios=scenarios,
            ),
            operation=ScenarioOperation.REGENERATE,
            config=MonteCarloConfig(
                trial_count=previous.trial_count,
                seed=previous.root_seed,
            ),
        )

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run_id: UUID,
    ) -> ScenarioSimulationRun:
        return await self._require_run(
            session,
            user_id=user_id,
            run_id=run_id,
        )

    async def compare(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run_id: UUID,
    ) -> ScenarioSimulationRun:
        return await self.get(
            session,
            user_id=user_id,
            run_id=run_id,
        )

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[ScenarioSimulationRun, ...]:
        return await self._repository.list_recent(
            session,
            user_id=user_id,
            limit=limit,
        )

    async def select(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run_id: UUID,
        command: ScenarioSelectionCommand,
    ) -> ScenarioSimulationRun:
        started_at = self._monitor.start()
        run = await self._require_run(
            session,
            user_id=user_id,
            run_id=run_id,
            for_update=True,
        )
        current = run.selected_scenario_id
        if current != command.expected_selected_scenario_id:
            self._monitor.record_failure(
                operation=ScenarioOperation.SELECT,
                reason=ScenarioFailureReason.SELECTION_CONFLICT,
                started_at=started_at,
            )
            raise _selection_conflict_error()
        try:
            if command.scenario_definition_id is None:
                if current is None:
                    raise ValueError("No scenario selection is active.")
                await self._repository.clear_selection(
                    session,
                    run=run,
                    user_id=user_id,
                    expected_scenario_definition_id=current,
                    occurred_at=self._clock.now(),
                )
                operation = ScenarioOperation.CLEAR_SELECTION
            else:
                await self._repository.select(
                    session,
                    run=run,
                    user_id=user_id,
                    scenario_definition_id=command.scenario_definition_id,
                    occurred_at=self._clock.now(),
                )
                operation = ScenarioOperation.SELECT
        except ValueError:
            self._monitor.record_failure(
                operation=ScenarioOperation.SELECT,
                reason=ScenarioFailureReason.SELECTION_CONFLICT,
                started_at=started_at,
            )
            raise _selection_conflict_error() from None
        self._monitor.record_selection(
            operation=operation,
            started_at=started_at,
        )
        return run

    async def _execute(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        command: ScenarioSimulationCommand,
        operation: ScenarioOperation,
        config: MonteCarloConfig | None,
    ) -> ScenarioSimulationRun:
        started_at = self._monitor.start()
        try:
            async with self._execution_guard.slot(user_id=user_id):
                validate_scenario_assumptions(command.scenarios)
                snapshot = await self._evidence.build(
                    session,
                    user_id=user_id,
                    source_plan_id=command.source_plan_id,
                    scenarios=command.scenarios,
                )
                analysis = await self._analyze(
                    snapshot,
                    config=config,
                )
                run = await self._repository.create(
                    session,
                    user_id=user_id,
                    snapshot=snapshot,
                    analysis=analysis,
                    occurred_at=self._clock.now(),
                )
        except ScenarioExecutionBusyError:
            self._monitor.record_failure(
                operation=operation,
                reason=ScenarioFailureReason.CAPACITY_EXHAUSTED,
                started_at=started_at,
            )
            raise ApplicationError(
                code="scenario_capacity_exhausted",
                message="Scenario simulation capacity is temporarily unavailable.",
                status_code=429,
            ) from None
        except ScenarioRateLimitError:
            self._monitor.record_failure(
                operation=operation,
                reason=ScenarioFailureReason.RATE_LIMITED,
                started_at=started_at,
            )
            raise ApplicationError(
                code="scenario_rate_limited",
                message="The scenario simulation request rate was exceeded.",
                status_code=429,
            ) from None
        except ApplicationError as error:
            self._monitor.record_failure(
                operation=operation,
                reason=(
                    ScenarioFailureReason.NOT_FOUND
                    if error.status_code == 404
                    else ScenarioFailureReason.EVIDENCE_UNAVAILABLE
                ),
                started_at=started_at,
            )
            raise
        except (TypeError, ValueError):
            self._monitor.record_failure(
                operation=operation,
                reason=ScenarioFailureReason.EVIDENCE_UNAVAILABLE,
                started_at=started_at,
            )
            raise _unavailable_error() from None
        self._monitor.record_simulation(
            run,
            operation=operation,
            started_at=started_at,
        )
        return run

    async def _analyze(
        self,
        snapshot: Any,
        *,
        config: MonteCarloConfig | None,
    ) -> ScenarioDecisionAnalysis:
        task = asyncio.create_task(
            asyncio.to_thread(
                self._analyzer,
                snapshot,
                config=config,
                solver=self._solver,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(task)
            except Exception:
                pass
            raise

    async def _require_run(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run_id: UUID,
        for_update: bool = False,
    ) -> ScenarioSimulationRun:
        run = await self._repository.get(
            session,
            user_id=user_id,
            run_id=run_id,
            for_update=for_update,
        )
        if run is None:
            raise ApplicationError(
                code="scenario_simulation_not_found",
                message="The requested scenario simulation was not found.",
                status_code=404,
            )
        return run


def _stored_scenarios(
    definitions: list[ScenarioDefinition],
) -> tuple[ScenarioAssumptions, ...]:
    scenarios = tuple(
        _stored_assumption(item.assumptions)
        for item in sorted(definitions, key=lambda value: value.ordinal)
        if item.assumptions is not None
    )
    validate_scenario_assumptions(scenarios)
    return scenarios


def _stored_assumption(value: dict[str, object] | None) -> ScenarioAssumptions:
    if value is None:
        raise ValueError("Stored user-defined scenario assumptions are required.")
    return ScenarioAssumptions(
        name=str(value["name"]),
        income_change_percent=_decimal(value.get("income_change_percent", "0")),
        expense_change_percent=_decimal(value.get("expense_change_percent", "0")),
        one_time_expenses=tuple(
            OneTimeExpenseAssumption(
                period_start=_date(item["period_start"]),
                amount=_decimal(item["amount"]),
            )
            for item in _objects(value.get("one_time_expenses", []))
        ),
        recurring_expense_adjustments=tuple(
            RecurringExpenseAdjustment(
                start_period=_date(item["start_period"]),
                end_period=_date(item["end_period"]),
                monthly_delta=_decimal(item["monthly_delta"]),
            )
            for item in _objects(value.get("recurring_expense_adjustments", []))
        ),
        debt_payment_adjustments=tuple(
            DebtPaymentAdjustment(
                start_period=_date(item["start_period"]),
                end_period=_date(item["end_period"]),
                monthly_delta=_decimal(item["monthly_delta"]),
            )
            for item in _objects(value.get("debt_payment_adjustments", []))
        ),
        income_interruptions=tuple(
            IncomeInterruptionAssumption(
                start_period=_date(item["start_period"]),
                end_period=_date(item["end_period"]),
                retained_income_percent=_decimal(
                    item["retained_income_percent"]
                ),
            )
            for item in _objects(value.get("income_interruptions", []))
        ),
        goal_adjustments=tuple(
            _stored_goal_adjustment(item)
            for item in _objects(value.get("goal_adjustments", []))
        ),
        emergency_fund_target_months=(
            _decimal(value["emergency_fund_target_months"])
            if value.get("emergency_fund_target_months") is not None
            else None
        ),
    )


def _stored_goal_adjustment(value: dict[str, object]) -> GoalScenarioAdjustment:
    return GoalScenarioAdjustment(
        goal_id=UUID(str(value["goal_id"])),
        target_amount=(
            _decimal(value["target_amount"])
            if value.get("target_amount") is not None
            else None
        ),
        target_date=(
            _date(value["target_date"])
            if value.get("target_date") is not None
            else None
        ),
        priority=(
            GoalPriority(str(value["priority"]))
            if value.get("priority") is not None
            else None
        ),
        monthly_contribution_delta=(
            _decimal(value["monthly_contribution_delta"])
            if value.get("monthly_contribution_delta") is not None
            else None
        ),
        pause_start=(
            _date(value["pause_start"])
            if value.get("pause_start") is not None
            else None
        ),
        pause_end=(
            _date(value["pause_end"])
            if value.get("pause_end") is not None
            else None
        ),
    )


def _objects(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TypeError("Stored scenario collections must contain objects.")
    return tuple(value)


def _date(value: object) -> date:
    return date.fromisoformat(str(value))


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _unavailable_error() -> ApplicationError:
    return ApplicationError(
        code="scenario_simulation_unavailable",
        message="Trusted evidence could not produce a safe scenario simulation.",
        status_code=422,
    )


def _selection_conflict_error() -> ApplicationError:
    return ApplicationError(
        code="scenario_selection_conflict",
        message="The scenario selection changed or is not valid for this run.",
        status_code=409,
    )
