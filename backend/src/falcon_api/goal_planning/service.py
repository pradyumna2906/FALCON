"""Application workflows for authenticated goal management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning.repository import GoalRepository, GoalValues
from falcon_api.goal_planning.semantics import (
    GoalPlanningErrorCode,
    goal_status_can_transition,
    normalize_goal_currency,
    trusted_local_date,
)
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


@dataclass(frozen=True, slots=True)
class GoalCreateCommand:
    name: str
    goal_type: GoalType
    target_amount: Decimal
    starting_amount: Decimal
    currency: str | None
    target_date: date
    priority: GoalPriority
    description: str | None


@dataclass(frozen=True, slots=True)
class GoalUpdateCommand:
    fields: frozenset[str]
    name: str | None = None
    goal_type: GoalType | None = None
    target_amount: Decimal | None = None
    starting_amount: Decimal | None = None
    currency: str | None = None
    target_date: date | None = None
    priority: GoalPriority | None = None
    description: str | None = None


class GoalService:
    """Own goal validation, owner isolation, and lifecycle transitions."""

    def __init__(
        self,
        *,
        repository: GoalRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or GoalRepository()
        self._clock = clock or SystemClock()

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        default_currency: str,
        trusted_timezone: str,
        command: GoalCreateCommand,
    ) -> Goal:
        now = self._clock.now()
        values = _validate_values(
            GoalValues(
                name=command.name.strip(),
                goal_type=GoalType(command.goal_type),
                target_amount=command.target_amount,
                starting_amount=command.starting_amount,
                currency=normalize_goal_currency(
                    command.currency or default_currency
                ),
                target_date=command.target_date,
                priority=GoalPriority(command.priority),
                description=_optional_text(command.description),
            ),
            local_today=trusted_local_date(
                instant=now,
                timezone=trusted_timezone,
            ),
        )
        return await self._repository.create(
            session,
            user_id=user_id,
            values=values,
            now=now,
        )

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
    ) -> Goal:
        goal = await self._repository.get(
            session,
            user_id=user_id,
            goal_id=goal_id,
        )
        if goal is None:
            raise _not_found()
        return goal

    async def list(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        status: GoalStatus | None,
        limit: int,
    ) -> tuple[Goal, ...]:
        return await self._repository.list(
            session,
            user_id=user_id,
            status=status,
            limit=limit,
        )

    async def update(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        trusted_timezone: str,
        command: GoalUpdateCommand,
    ) -> Goal:
        now = self._clock.now()
        goal = await self._owned_for_update(
            session,
            user_id=user_id,
            goal_id=goal_id,
        )
        _require_active(goal)
        values = _validate_values(
            _updated_values(goal=goal, command=command),
            local_today=trusted_local_date(
                instant=now,
                timezone=trusted_timezone,
            ),
        )
        return await self._repository.replace(
            session,
            user_id=user_id,
            goal=goal,
            values=values,
            now=now,
        )

    async def complete(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
    ) -> Goal:
        return await self._transition(
            session,
            user_id=user_id,
            goal_id=goal_id,
            target=GoalStatus.COMPLETED,
        )

    async def cancel(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
    ) -> Goal:
        return await self._transition(
            session,
            user_id=user_id,
            goal_id=goal_id,
            target=GoalStatus.CANCELLED,
        )

    async def _transition(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        target: GoalStatus,
    ) -> Goal:
        goal = await self._owned_for_update(
            session,
            user_id=user_id,
            goal_id=goal_id,
        )
        if not goal_status_can_transition(current=goal.status, target=target):
            raise _inactive()
        return await self._repository.transition(
            session,
            user_id=user_id,
            goal=goal,
            status=target,
            now=self._clock.now(),
        )

    async def _owned_for_update(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
    ) -> Goal:
        goal = await self._repository.get(
            session,
            user_id=user_id,
            goal_id=goal_id,
            for_update=True,
        )
        if goal is None:
            raise _not_found()
        return goal


def _updated_values(*, goal: Goal, command: GoalUpdateCommand) -> GoalValues:
    fields = command.fields
    return GoalValues(
        name=(command.name or "").strip() if "name" in fields else goal.name,
        goal_type=(
            GoalType(command.goal_type)
            if "goal_type" in fields and command.goal_type is not None
            else GoalType(goal.goal_type)
        ),
        target_amount=(
            command.target_amount
            if "target_amount" in fields and command.target_amount is not None
            else goal.target_amount
        ),
        starting_amount=(
            command.starting_amount
            if "starting_amount" in fields and command.starting_amount is not None
            else goal.starting_amount
        ),
        currency=(
            normalize_goal_currency(command.currency or "")
            if "currency" in fields
            else goal.currency
        ),
        target_date=(
            command.target_date
            if "target_date" in fields and command.target_date is not None
            else goal.target_date
        ),
        priority=(
            GoalPriority(command.priority)
            if "priority" in fields and command.priority is not None
            else GoalPriority(goal.priority)
        ),
        description=(
            _optional_text(command.description)
            if "description" in fields
            else goal.description
        ),
    )


def _validate_values(values: GoalValues, *, local_today: date) -> GoalValues:
    if not values.name:
        raise ApplicationError(
            code=GoalPlanningErrorCode.INVALID_NAME.value,
            message="A goal name is required.",
            status_code=422,
        )
    if (
        not values.target_amount.is_finite()
        or not values.starting_amount.is_finite()
        or values.target_amount <= 0
        or values.starting_amount < 0
        or values.starting_amount > values.target_amount
    ):
        raise _invalid_amount(
            "Goal amounts must be finite, non-negative, and within the target."
        )
    if values.target_date <= local_today:
        raise ApplicationError(
            code=GoalPlanningErrorCode.INVALID_DEADLINE.value,
            message="An active goal deadline must be after today.",
            status_code=422,
        )
    return values


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _require_active(goal: Goal) -> None:
    if GoalStatus(goal.status) is not GoalStatus.ACTIVE:
        raise _inactive()


def _not_found() -> ApplicationError:
    return ApplicationError(
        code=GoalPlanningErrorCode.NOT_FOUND.value,
        message="The requested goal was not found.",
        status_code=404,
    )


def _inactive() -> ApplicationError:
    return ApplicationError(
        code=GoalPlanningErrorCode.INACTIVE.value,
        message="Only an active goal may be changed.",
        status_code=409,
    )


def _invalid_amount(message: str) -> ApplicationError:
    return ApplicationError(
        code=GoalPlanningErrorCode.INVALID_AMOUNT.value,
        message=message,
        status_code=422,
    )
