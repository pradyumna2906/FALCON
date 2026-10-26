"""User-scoped persistence for transaction setup resources."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import AccountType
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class AccountValues:
    """Validated values required to provision one account."""

    name: str
    account_type: AccountType
    institution_name: str | None
    masked_reference: str | None
    currency: str
    opening_balance: Decimal
    opening_balance_date: date


class LedgerRepository:
    """Persist and resolve ledger setup data without crossing users."""

    async def create_account(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        values: AccountValues,
        now: datetime,
    ) -> Account:
        """Add one active user-owned account and flush it."""
        account = Account(
            id=uuid4(),
            user_id=user_id,
            name=values.name,
            account_type=values.account_type,
            institution_name=values.institution_name,
            masked_reference=values.masked_reference,
            currency=values.currency,
            opening_balance=values.opening_balance,
            opening_balance_date=values.opening_balance_date,
            archived_at=None,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        await session.flush()
        return account

    async def list_accounts(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> tuple[Account, ...]:
        """Return only active accounts owned by the specified user."""
        statement = (
            select(Account)
            .where(
                Account.user_id == user_id,
                Account.archived_at.is_(None),
            )
            .order_by(Account.created_at.asc(), Account.id.asc())
        )
        result = await session.scalars(statement)
        return tuple(result.all())

    async def list_categories(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> tuple[Category, ...]:
        """Return active system and same-user private categories."""
        statement = (
            select(Category)
            .where(
                Category.archived_at.is_(None),
                or_(
                    Category.is_system.is_(True),
                    Category.user_id == user_id,
                ),
            )
            .order_by(
                Category.kind.asc(),
                Category.display_order.asc(),
                Category.name.asc(),
                Category.id.asc(),
            )
        )
        result = await session.scalars(statement)
        return tuple(result.all())
