"""Application workflows for transaction setup resources."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final
from uuid import UUID

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.ledger.repository import AccountValues, LedgerRepository
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import AccountType
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


_ACCOUNT_NAME_UNIQUE_CONSTRAINT: Final = "uq_accounts_user_name"


@dataclass(frozen=True, slots=True)
class AccountCreateCommand:
    """Validated public values used to provision an account."""

    name: str
    account_type: AccountType
    institution_name: str | None
    masked_reference: str | None
    currency: str | None
    opening_balance: Decimal
    opening_balance_date: date


class LedgerService:
    """Own account provisioning and available-category discovery."""

    def __init__(
        self,
        *,
        repository: LedgerRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or LedgerRepository()
        self._clock = clock or SystemClock()

    async def create_account(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        default_currency: str,
        command: AccountCreateCommand,
    ) -> Account:
        """Provision one account using the principal's currency by default."""
        try:
            async with session.begin_nested():
                return await self._repository.create_account(
                    session,
                    user_id=user_id,
                    values=AccountValues(
                        name=command.name,
                        account_type=command.account_type,
                        institution_name=command.institution_name,
                        masked_reference=command.masked_reference,
                        currency=command.currency or default_currency,
                        opening_balance=command.opening_balance,
                        opening_balance_date=command.opening_balance_date,
                    ),
                    now=self._clock.now(),
                )
        except IntegrityError as exc:
            if _constraint_name(exc) != _ACCOUNT_NAME_UNIQUE_CONSTRAINT:
                raise
            raise ApplicationError(
                code="account_name_conflict",
                message="An active or archived account already uses this name.",
                status_code=409,
            ) from None

    async def list_accounts(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> tuple[Account, ...]:
        """Return all active accounts owned by the principal."""
        return await self._repository.list_accounts(session, user_id=user_id)

    async def list_categories(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> tuple[Category, ...]:
        """Return categories that the principal may assign."""
        return await self._repository.list_categories(session, user_id=user_id)


def _constraint_name(exc: IntegrityError) -> str | None:
    original = exc.orig
    diagnostic = getattr(original, "diag", None)
    return getattr(diagnostic, "constraint_name", None)
