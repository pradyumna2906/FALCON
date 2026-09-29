"""User-scoped persistence operations for financial profiles."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
)
from falcon_api.models.user import FinancialProfile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class FinancialProfileValues:
    """Validated values persisted as one planning-context snapshot."""

    income_pattern: IncomePattern | None
    income_stability: IncomeStability | None
    has_household_responsibilities: bool
    dependant_count: int
    emergency_fund_target_months: Decimal | None
    completion_status: ProfileCompletionStatus


class FinancialProfileRepository:
    """Persist profiles without crossing the authenticated user boundary."""

    async def get_by_user_id(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        for_update: bool = False,
    ) -> FinancialProfile | None:
        """Return only the profile owned by the specified user."""
        statement = select(FinancialProfile).where(
            FinancialProfile.user_id == user_id
        )

        if for_update:
            statement = statement.with_for_update()

        return await session.scalar(statement)

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        values: FinancialProfileValues,
        now: datetime,
    ) -> FinancialProfile:
        """Add one new profile for the specified user and flush it."""
        profile = FinancialProfile(
            id=uuid4(),
            user_id=user_id,
            income_pattern=values.income_pattern,
            income_stability=values.income_stability,
            has_household_responsibilities=(
                values.has_household_responsibilities
            ),
            dependant_count=values.dependant_count,
            emergency_fund_target_months=(
                values.emergency_fund_target_months
            ),
            completion_status=values.completion_status,
            created_at=now,
            updated_at=now,
        )
        session.add(profile)
        await session.flush()

        return profile

    async def replace(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        profile: FinancialProfile,
        values: FinancialProfileValues,
        now: datetime,
    ) -> FinancialProfile:
        """Replace mutable values on a profile owned by the user."""
        if profile.user_id != user_id:
            raise ValueError(
                "Financial profile does not belong to the specified user."
            )

        profile.income_pattern = values.income_pattern
        profile.income_stability = values.income_stability
        profile.has_household_responsibilities = (
            values.has_household_responsibilities
        )
        profile.dependant_count = values.dependant_count
        profile.emergency_fund_target_months = (
            values.emergency_fund_target_months
        )
        profile.completion_status = values.completion_status
        profile.updated_at = now
        await session.flush()

        return profile
