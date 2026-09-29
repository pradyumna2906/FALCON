"""Owner-scoped goal contributions and exact progress application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.types import money
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning.progress import GoalProgress, calculate_goal_progress
from falcon_api.goal_planning.repository import GoalRepository
from falcon_api.goal_planning.semantics import (
    GoalPlanningErrorCode,
    trusted_local_date,
)
from falcon_api.models.account import Account
from falcon_api.models.enums import (
    ContributionSourceType,
    GoalStatus,
    TransactionStatus,
)
from falcon_api.models.ledger import Transaction
from falcon_api.models.planning import Goal, GoalContribution


@dataclass(frozen=True, slots=True)
class ContributionCreateCommand:
    """Validated public intent for one contribution."""

    source_type: ContributionSourceType
    amount: Decimal
    contribution_date: date | None
    transaction_id: UUID | None
    note: str | None


@dataclass(frozen=True, slots=True)
class TransactionAllocationEvidence:
    """Trusted transaction facts needed for a linked contribution."""

    transaction_id: UUID
    amount: Decimal
    transaction_date: date
    currency: str
    status: TransactionStatus


class ContributionRepository:
    """Persist contributions with owner, goal, and transaction scope."""

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        command: ContributionCreateCommand,
        contribution_date: date,
        now: datetime,
    ) -> GoalContribution:
        contribution = GoalContribution(
            id=uuid4(),
            user_id=user_id,
            goal_id=goal_id,
            transaction_id=command.transaction_id,
            amount=money(command.amount),
            contribution_date=contribution_date,
            source_type=ContributionSourceType(command.source_type),
            note=_optional_text(command.note),
            created_at=now,
            updated_at=now,
        )
        session.add(contribution)
        await session.flush()
        return contribution

    async def list(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
    ) -> tuple[GoalContribution, ...]:
        statement = (
            select(GoalContribution)
            .where(
                GoalContribution.user_id == user_id,
                GoalContribution.goal_id == goal_id,
            )
            .order_by(
                GoalContribution.contribution_date.asc(),
                GoalContribution.created_at.asc(),
                GoalContribution.id.asc(),
            )
        )
        rows = await session.scalars(statement)
        return tuple(rows.all())

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        contribution_id: UUID,
        for_update: bool = False,
    ) -> GoalContribution | None:
        statement = select(GoalContribution).where(
            GoalContribution.user_id == user_id,
            GoalContribution.goal_id == goal_id,
            GoalContribution.id == contribution_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def delete(
        self,
        session: AsyncSession,
        *,
        contribution: GoalContribution,
    ) -> None:
        await session.delete(contribution)
        await session.flush()

    async def sum_for_goal(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        cutoff_at: datetime | None = None,
    ) -> Decimal:
        statement = select(func.coalesce(func.sum(GoalContribution.amount), 0)).where(
            GoalContribution.user_id == user_id,
            GoalContribution.goal_id == goal_id,
        )
        if cutoff_at is not None:
            statement = statement.where(
                GoalContribution.created_at <= cutoff_at,
                GoalContribution.updated_at <= cutoff_at,
            )
        return money(Decimal(await session.scalar(statement) or 0))

    async def transaction_evidence_for_update(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
    ) -> TransactionAllocationEvidence | None:
        statement = (
            select(
                Transaction.id,
                Transaction.amount,
                Transaction.transaction_date,
                Transaction.status,
                Account.currency,
            )
            .select_from(Transaction)
            .join(
                Account,
                and_(
                    Account.user_id == Transaction.user_id,
                    Account.id == Transaction.account_id,
                ),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.id == transaction_id,
            )
            .with_for_update(of=Transaction)
        )
        row = (await session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return TransactionAllocationEvidence(
            transaction_id=row["id"],
            amount=money(abs(Decimal(row["amount"]))),
            transaction_date=row["transaction_date"],
            currency=row["currency"],
            status=TransactionStatus(row["status"]),
        )

    async def sum_for_transaction(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
        excluding_contribution_id: UUID | None = None,
    ) -> Decimal:
        statement = select(func.coalesce(func.sum(GoalContribution.amount), 0)).where(
            GoalContribution.user_id == user_id,
            GoalContribution.transaction_id == transaction_id,
        )
        if excluding_contribution_id is not None:
            statement = statement.where(
                GoalContribution.id != excluding_contribution_id
            )
        return money(Decimal(await session.scalar(statement) or 0))


class ContributionService:
    """Validate contribution provenance and keep progress allocation-safe."""

    def __init__(
        self,
        *,
        repository: ContributionRepository | None = None,
        goal_repository: GoalRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or ContributionRepository()
        self._goal_repository = goal_repository or GoalRepository()
        self._clock = clock or SystemClock()

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        trusted_timezone: str,
        command: ContributionCreateCommand,
    ) -> GoalContribution:
        now = self._clock.now()
        local_today = trusted_local_date(
            instant=now,
            timezone=trusted_timezone,
        )
        goal = await self._owned_goal(
            session,
            user_id=user_id,
            goal_id=goal_id,
            for_update=True,
        )
        _require_active(goal)
        amount = _valid_amount(command.amount)
        contribution_date = await self._resolve_source(
            session,
            user_id=user_id,
            goal=goal,
            command=command,
            local_today=local_today,
            amount=amount,
        )
        allocated = await self._repository.sum_for_goal(
            session,
            user_id=user_id,
            goal_id=goal.id,
        )
        available = money(goal.target_amount - goal.starting_amount - allocated)
        if amount > available:
            raise _error(
                GoalPlanningErrorCode.CONTRIBUTION_EXCEEDS_REMAINING,
                "The contribution exceeds the goal's remaining amount.",
                409,
            )
        return await self._repository.create(
            session,
            user_id=user_id,
            goal_id=goal.id,
            command=command,
            contribution_date=contribution_date,
            now=now,
        )

    async def list(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
    ) -> tuple[GoalContribution, ...]:
        await self._owned_goal(session, user_id=user_id, goal_id=goal_id)
        return await self._repository.list(
            session,
            user_id=user_id,
            goal_id=goal_id,
        )

    async def delete(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        contribution_id: UUID,
    ) -> None:
        goal = await self._owned_goal(
            session,
            user_id=user_id,
            goal_id=goal_id,
            for_update=True,
        )
        _require_active(goal)
        contribution = await self._repository.get(
            session,
            user_id=user_id,
            goal_id=goal_id,
            contribution_id=contribution_id,
            for_update=True,
        )
        if contribution is None:
            raise _error(
                GoalPlanningErrorCode.CONTRIBUTION_NOT_FOUND,
                "The requested contribution was not found.",
                404,
            )
        if contribution.transaction_id is not None:
            await self._repository.transaction_evidence_for_update(
                session,
                user_id=user_id,
                transaction_id=contribution.transaction_id,
            )
        await self._repository.delete(session, contribution=contribution)

    async def progress(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        trusted_timezone: str,
    ) -> GoalProgress:
        goal = await self._owned_goal(
            session,
            user_id=user_id,
            goal_id=goal_id,
        )
        contributed = await self._repository.sum_for_goal(
            session,
            user_id=user_id,
            goal_id=goal.id,
        )
        return calculate_goal_progress(
            goal=goal,
            contribution_amount=contributed,
            calculated_on=trusted_local_date(
                instant=self._clock.now(),
                timezone=trusted_timezone,
            ),
        )

    async def _owned_goal(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_id: UUID,
        for_update: bool = False,
    ) -> Goal:
        goal = await self._goal_repository.get(
            session,
            user_id=user_id,
            goal_id=goal_id,
            for_update=for_update,
        )
        if goal is None:
            raise _error(
                GoalPlanningErrorCode.NOT_FOUND,
                "The requested goal was not found.",
                404,
            )
        return goal

    async def _resolve_source(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal: Goal,
        command: ContributionCreateCommand,
        local_today: date,
        amount: Decimal,
    ) -> date:
        source = ContributionSourceType(command.source_type)
        if source is ContributionSourceType.TRANSACTION:
            if command.transaction_id is None or command.contribution_date is not None:
                raise _invalid_contribution(
                    "Transaction contributions derive their date from the transaction."
                )
            evidence = await self._repository.transaction_evidence_for_update(
                session,
                user_id=user_id,
                transaction_id=command.transaction_id,
            )
            if evidence is None or evidence.status is not TransactionStatus.POSTED:
                raise _invalid_contribution(
                    "A posted owner-scoped transaction is required."
                )
            if evidence.currency != goal.currency:
                raise _error(
                    GoalPlanningErrorCode.CURRENCY_MISMATCH,
                    "The transaction and goal currencies must match.",
                    422,
                )
            if evidence.transaction_date > local_today:
                raise _invalid_contribution(
                    "A linked transaction date cannot be in the future."
                )
            allocated = await self._repository.sum_for_transaction(
                session,
                user_id=user_id,
                transaction_id=evidence.transaction_id,
            )
            if money(allocated + amount) > evidence.amount:
                raise _error(
                    GoalPlanningErrorCode.TRANSACTION_OVERALLOCATED,
                    "Goal allocations exceed the linked transaction amount.",
                    409,
                )
            return evidence.transaction_date

        if command.transaction_id is not None or command.contribution_date is None:
            raise _invalid_contribution(
                "Manual and opening-balance contributions require a date and "
                "no transaction."
            )
        if command.contribution_date > local_today:
            raise _invalid_contribution("A contribution date cannot be in the future.")
        return command.contribution_date


def _valid_amount(value: Decimal) -> Decimal:
    if not value.is_finite() or value <= 0:
        raise _invalid_contribution(
            "A contribution amount must be positive and finite."
        )
    return money(value)


def _require_active(goal: Goal) -> None:
    if GoalStatus(goal.status) is not GoalStatus.ACTIVE:
        raise _error(
            GoalPlanningErrorCode.INACTIVE,
            "Only an active goal may be changed.",
            409,
        )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _invalid_contribution(message: str) -> ApplicationError:
    return _error(GoalPlanningErrorCode.INVALID_CONTRIBUTION, message, 422)


def _error(
    code: GoalPlanningErrorCode,
    message: str,
    status_code: int,
) -> ApplicationError:
    return ApplicationError(
        code=code.value,
        message=message,
        status_code=status_code,
    )
