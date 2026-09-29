"""Application workflows for authenticated financial profiles."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
)
from falcon_api.models.user import FinancialProfile
from falcon_api.profile.repository import (
    FinancialProfileRepository,
    FinancialProfileValues,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


_PROFILE_NOT_FOUND_CODE: Final = "profile_not_found"
_PROFILE_USER_UNIQUE_CONSTRAINT: Final = (
    "uq_financial_profiles_user_id"
)


@dataclass(frozen=True, slots=True)
class FinancialProfileCommand:
    """Validated planning values submitted for replacement."""

    income_pattern: IncomePattern | None
    income_stability: IncomeStability | None
    has_household_responsibilities: bool
    dependant_count: int
    emergency_fund_target_months: Decimal | None


@dataclass(frozen=True, slots=True)
class FinancialProfileMutationResult:
    """Profile state and creation metadata returned by replacement."""

    profile: FinancialProfile
    created: bool


class FinancialProfileService:
    """Own profile completion and create-or-replace policy."""

    def __init__(
        self,
        *,
        repository: FinancialProfileRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or FinancialProfileRepository()
        self._clock = clock or SystemClock()

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> FinancialProfile:
        """Return the user's current profile or a public not-found error."""
        profile = await self._repository.get_by_user_id(
            session,
            user_id=user_id,
        )

        if profile is None:
            raise _profile_not_found()

        return profile

    async def put(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        command: FinancialProfileCommand,
    ) -> FinancialProfileMutationResult:
        """Create or idempotently replace the user's planning context."""
        values = _profile_values(command)
        now = self._clock.now()
        profile = await self._repository.get_by_user_id(
            session,
            user_id=user_id,
            for_update=True,
        )

        if profile is not None:
            replaced = await self._repository.replace(
                session,
                user_id=user_id,
                profile=profile,
                values=values,
                now=now,
            )
            return FinancialProfileMutationResult(
                profile=replaced,
                created=False,
            )

        try:
            async with session.begin_nested():
                created = await self._repository.create(
                    session,
                    user_id=user_id,
                    values=values,
                    now=now,
                )
        except IntegrityError as exc:
            if _constraint_name(exc) != _PROFILE_USER_UNIQUE_CONSTRAINT:
                raise

            return await self._replace_after_creation_race(
                session,
                user_id=user_id,
                values=values,
                now=now,
                original_error=exc,
            )

        return FinancialProfileMutationResult(
            profile=created,
            created=True,
        )

    async def _replace_after_creation_race(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        values: FinancialProfileValues,
        now: datetime,
        original_error: IntegrityError,
    ) -> FinancialProfileMutationResult:
        """Replace the row committed by a concurrent first update."""
        profile = await self._repository.get_by_user_id(
            session,
            user_id=user_id,
            for_update=True,
        )

        if profile is None:
            raise original_error

        replaced = await self._repository.replace(
            session,
            user_id=user_id,
            profile=profile,
            values=values,
            now=now,
        )
        return FinancialProfileMutationResult(
            profile=replaced,
            created=False,
        )


def _profile_values(
    command: FinancialProfileCommand,
) -> FinancialProfileValues:
    completion_status = (
        ProfileCompletionStatus.COMPLETE
        if command.income_pattern is not None
        and command.income_stability is not None
        else ProfileCompletionStatus.DRAFT
    )
    return FinancialProfileValues(
        income_pattern=command.income_pattern,
        income_stability=command.income_stability,
        has_household_responsibilities=(
            command.has_household_responsibilities
        ),
        dependant_count=command.dependant_count,
        emergency_fund_target_months=(
            command.emergency_fund_target_months
        ),
        completion_status=completion_status,
    )


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _profile_not_found() -> ApplicationError:
    return ApplicationError(
        code=_PROFILE_NOT_FOUND_CODE,
        message="A financial profile has not been created.",
        status_code=404,
    )
