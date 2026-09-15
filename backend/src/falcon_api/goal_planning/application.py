"""Transactional orchestration for persistent multi-goal optimization plans."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning.monitoring import (
    GoalPlanMonitor,
    GoalPlanOperation,
)
from falcon_api.goal_planning.optimizer import LinearProgramSolver
from falcon_api.goal_planning.persistence import GoalPlanRepository
from falcon_api.goal_planning.plan import (
    GoalPlanStrategy,
    build_goal_optimization_plan,
)
from falcon_api.goal_planning.snapshot import GoalPlanningSnapshotService
from falcon_api.models.enums import GoalPlanEventSource, GoalPlanStatus
from falcon_api.models.goal_plan import GoalPlanRun


@dataclass(frozen=True, slots=True)
class GoalPlanGenerationCommand:
    """Trusted inputs permitted at the plan-generation boundary."""

    currency: str
    trusted_timezone: str


class MultiGoalOptimizationService:
    """Freeze evidence, optimize, persist, and manage immutable plan decisions."""

    def __init__(
        self,
        *,
        snapshot_service: GoalPlanningSnapshotService | None = None,
        repository: GoalPlanRepository | None = None,
        solver: LinearProgramSolver | None = None,
        monitor: GoalPlanMonitor | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._snapshots = snapshot_service or GoalPlanningSnapshotService(
            clock=self._clock
        )
        self._repository = repository or GoalPlanRepository()
        self._solver = solver
        self._monitor = monitor or GoalPlanMonitor()

    async def generate(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        command: GoalPlanGenerationCommand,
    ) -> GoalPlanRun:
        started_at = self._monitor.start()
        run = await self._build_and_persist(
            session,
            user_id=user_id,
            command=command,
            predecessor_plan_id=None,
        )
        self._monitor.record_generation(
            run,
            operation=GoalPlanOperation.GENERATE,
            started_at=started_at,
        )
        return run

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> GoalPlanRun:
        return await self._require_plan(
            session,
            user_id=user_id,
            plan_id=plan_id,
        )

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[GoalPlanRun, ...]:
        return await self._repository.list_recent(
            session,
            user_id=user_id,
            limit=limit,
        )

    async def approve(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> GoalPlanRun:
        started_at = self._monitor.start()
        run = await self._require_plan(
            session,
            user_id=user_id,
            plan_id=plan_id,
            for_update=True,
        )
        if run.status is not GoalPlanStatus.GENERATED:
            raise _transition_error()
        if run.strategy == GoalPlanStrategy.BLOCKED.value:
            raise ApplicationError(
                code="goal_plan_not_approvable",
                message="A financially blocked plan cannot be approved.",
                status_code=409,
            )
        try:
            await self._repository.transition(
                session,
                run=run,
                user_id=user_id,
                expected_status=GoalPlanStatus.GENERATED,
                new_status=GoalPlanStatus.APPROVED,
                source=GoalPlanEventSource.USER,
                occurred_at=self._clock.now(),
                successor_plan_id=None,
                reason_code="user_approved_plan",
            )
        except ValueError:
            raise _transition_error() from None
        self._monitor.record_transition(
            operation=GoalPlanOperation.APPROVE,
            status=GoalPlanStatus.APPROVED,
            started_at=started_at,
        )
        return run

    async def reject(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> GoalPlanRun:
        started_at = self._monitor.start()
        run = await self._require_plan(
            session,
            user_id=user_id,
            plan_id=plan_id,
            for_update=True,
        )
        if run.status is not GoalPlanStatus.GENERATED:
            raise _transition_error()
        try:
            await self._repository.transition(
                session,
                run=run,
                user_id=user_id,
                expected_status=GoalPlanStatus.GENERATED,
                new_status=GoalPlanStatus.REJECTED,
                source=GoalPlanEventSource.USER,
                occurred_at=self._clock.now(),
                successor_plan_id=None,
                reason_code="user_rejected_plan",
            )
        except ValueError:
            raise _transition_error() from None
        self._monitor.record_transition(
            operation=GoalPlanOperation.REJECT,
            status=GoalPlanStatus.REJECTED,
            started_at=started_at,
        )
        return run

    async def regenerate(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        plan_id: UUID,
        trusted_timezone: str,
    ) -> GoalPlanRun:
        started_at = self._monitor.start()
        previous = await self._require_plan(
            session,
            user_id=user_id,
            plan_id=plan_id,
            for_update=True,
        )
        previous_status = previous.status
        if previous_status not in {
            GoalPlanStatus.GENERATED,
            GoalPlanStatus.APPROVED,
        }:
            raise _transition_error()
        run = await self._build_and_persist(
            session,
            user_id=user_id,
            command=GoalPlanGenerationCommand(
                currency=previous.currency,
                trusted_timezone=trusted_timezone,
            ),
            predecessor_plan_id=previous.id,
        )
        try:
            await self._repository.transition(
                session,
                run=previous,
                user_id=user_id,
                expected_status=previous_status,
                new_status=GoalPlanStatus.SUPERSEDED,
                source=GoalPlanEventSource.SYSTEM,
                occurred_at=self._clock.now(),
                successor_plan_id=run.id,
                reason_code="plan_regenerated",
            )
        except ValueError:
            raise _transition_error() from None
        self._monitor.record_generation(
            run,
            operation=GoalPlanOperation.REGENERATE,
            started_at=started_at,
        )
        return run

    async def _build_and_persist(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        command: GoalPlanGenerationCommand,
        predecessor_plan_id: UUID | None,
    ) -> GoalPlanRun:
        try:
            snapshot = await self._snapshots.build(
                session,
                user_id=user_id,
                currency=command.currency,
                trusted_timezone=command.trusted_timezone,
            )
            plan = build_goal_optimization_plan(
                snapshot,
                solver=self._solver,
            )
            return await self._repository.create(
                session,
                user_id=user_id,
                snapshot=snapshot,
                plan=plan,
                occurred_at=self._clock.now(),
                predecessor_plan_id=predecessor_plan_id,
            )
        except ValueError:
            raise ApplicationError(
                code="goal_plan_unavailable",
                message="The available evidence could not produce a safe goal plan.",
                status_code=422,
            ) from None

    async def _require_plan(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        plan_id: UUID,
        for_update: bool = False,
    ) -> GoalPlanRun:
        run = await self._repository.get(
            session,
            user_id=user_id,
            plan_id=plan_id,
            for_update=for_update,
        )
        if run is None:
            raise ApplicationError(
                code="goal_plan_not_found",
                message="The requested goal plan was not found.",
                status_code=404,
            )
        return run


def _transition_error() -> ApplicationError:
    return ApplicationError(
        code="goal_plan_transition_conflict",
        message="The goal plan lifecycle does not permit this operation.",
        status_code=409,
    )
