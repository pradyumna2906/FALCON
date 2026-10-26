"""Owner-scoped persistence for Phase 10 goal management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


@dataclass(frozen=True, slots=True)
class GoalValues:
    """Complete validated values for one user-owned goal."""

    name: str
    goal_type: GoalType
    target_amount: Decimal
    starting_amount: Decimal
    currency: str
    target_date: date
    priority: GoalPriority
    description: str | None


class GoalRepository:
    """Persist goals without allowing identifier-only cross-owner access."""

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        values: GoalValues,
        now: datetime,
    ) -> Goal:
        """Add one active goal for the trusted owner."""
        goal = Goal(
            id=uuid4(),
            user_id=user_id,
            name=values.name,
            goal_type=values.goal_type,
            target_amount=values.target_amount,
            starting_amount=values.starting_amount,
            currency=values.currency,
            target_date=values.target_date,
            priority=values.priority,
            status=GoalStatus.ACTIVE,
            description=values.description,
            created_at=now,
            updated_at=now,
        )
        session.add(goal)
        await session.flush()
        return goal

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        for_update: bool = False,
    ) -> Goal | None:
        """Return a goal only when both its owner and identifier match."""
        statement = select(Goal).where(
            Goal.user_id == user_id,
            Goal.id == goal_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def list(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        status: GoalStatus | None,
        limit: int,
    ) -> tuple[Goal, ...]:
        """List owned goals in stable lifecycle, priority, and deadline order."""
        status_order = case(
            (Goal.status == GoalStatus.ACTIVE, 0),
            (Goal.status == GoalStatus.COMPLETED, 1),
            else_=2,
        )
        priority_order = case(
            (Goal.priority == GoalPriority.CRITICAL, 0),
            (Goal.priority == GoalPriority.HIGH, 1),
            (Goal.priority == GoalPriority.MEDIUM, 2),
            else_=3,
        )
        statement = select(Goal).where(Goal.user_id == user_id)
        if status is not None:
            statement = statement.where(Goal.status == status)
        statement = statement.order_by(
            status_order,
            priority_order,
            Goal.target_date.asc(),
            Goal.created_at.asc(),
            Goal.id.asc(),
        ).limit(limit)
        result = await session.scalars(statement)
        return tuple(result.all())

    async def replace(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal: Goal,
        values: GoalValues,
        now: datetime,
    ) -> Goal:
        """Replace mutable values after an owner-scoped row lock."""
        self._assert_owner(goal=goal, user_id=user_id)
        goal.name = values.name
        goal.goal_type = values.goal_type
        goal.target_amount = values.target_amount
        goal.starting_amount = values.starting_amount
        goal.currency = values.currency
        goal.target_date = values.target_date
        goal.priority = values.priority
        goal.description = values.description
        goal.updated_at = now
        await session.flush()
        return goal

    async def transition(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal: Goal,
        status: GoalStatus,
        now: datetime,
    ) -> Goal:
        """Persist one service-authorized terminal lifecycle transition."""
        self._assert_owner(goal=goal, user_id=user_id)
        goal.status = status
        goal.updated_at = now
        await session.flush()
        return goal

    @staticmethod
    def _assert_owner(*, goal: Goal, user_id: UUID) -> None:
        if goal.user_id != user_id:
            raise ValueError("Goal does not belong to the specified user.")
