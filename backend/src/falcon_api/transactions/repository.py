"""User-scoped persistence operations for the transaction ledger."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import (
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.ledger import Transaction, TransferGroup
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class TransactionValues:
    """Validated complete values for one new ledger entry."""

    account_id: UUID
    category_id: UUID | None
    import_job_id: UUID | None
    transfer_group_id: UUID | None
    transaction_type: TransactionType
    amount: Decimal
    transaction_date: date
    description: str
    merchant_name: str | None
    source_type: TransactionSourceType
    external_source_hash: str | None
    status: TransactionStatus
    is_user_modified: bool


@dataclass(frozen=True, slots=True)
class TransactionMutableValues:
    """Publicly mutable values that preserve ledger provenance."""

    account_id: UUID
    category_id: UUID | None
    transaction_type: TransactionType
    amount: Decimal
    transaction_date: date
    description: str
    merchant_name: str | None


@dataclass(frozen=True, slots=True)
class TransactionFilters:
    """Normalized optional filters for one user's timeline."""

    account_id: UUID | None = None
    category_id: UUID | None = None
    transaction_type: TransactionType | None = None
    status: TransactionStatus | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True, slots=True)
class TransactionCursor:
    """Decoded keyset position for descending ledger pagination."""

    transaction_date: date
    transaction_id: UUID


@dataclass(frozen=True, slots=True)
class TransactionSlice:
    """One bounded repository slice and whether another row exists."""

    items: tuple[Transaction, ...]
    has_more: bool


class TransactionRepository:
    """Persist ledger data without crossing authenticated ownership."""

    async def get_active_account(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        account_id: UUID,
        for_update: bool = False,
    ) -> Account | None:
        """Return one active account owned by the specified user."""
        statement = select(Account).where(
            Account.user_id == user_id,
            Account.id == account_id,
            Account.archived_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def get_active_category(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        category_id: UUID,
    ) -> Category | None:
        """Return an active system or same-user private category."""
        allowed_owner = or_(
            and_(
                Category.is_system.is_(True),
                Category.user_id.is_(None),
            ),
            and_(
                Category.is_system.is_(False),
                Category.user_id == user_id,
            ),
        )
        statement = select(Category).where(
            Category.id == category_id,
            Category.archived_at.is_(None),
            allowed_owner,
        )
        return await session.scalar(statement)

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
        for_update: bool = False,
    ) -> Transaction | None:
        """Return one transaction owned by the specified user."""
        statement = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.id == transaction_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def list_by_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        filters: TransactionFilters,
        cursor: TransactionCursor | None,
        limit: int,
    ) -> TransactionSlice:
        """Return a deterministic descending keyset slice."""
        predicates = [Transaction.user_id == user_id]
        if filters.account_id is not None:
            predicates.append(Transaction.account_id == filters.account_id)
        if filters.category_id is not None:
            predicates.append(Transaction.category_id == filters.category_id)
        if filters.transaction_type is not None:
            predicates.append(
                Transaction.transaction_type == filters.transaction_type
            )
        if filters.status is not None:
            predicates.append(Transaction.status == filters.status)
        if filters.date_from is not None:
            predicates.append(
                Transaction.transaction_date >= filters.date_from
            )
        if filters.date_to is not None:
            predicates.append(Transaction.transaction_date <= filters.date_to)
        if cursor is not None:
            predicates.append(
                or_(
                    Transaction.transaction_date < cursor.transaction_date,
                    and_(
                        Transaction.transaction_date
                        == cursor.transaction_date,
                        Transaction.id < cursor.transaction_id,
                    ),
                )
            )

        statement = (
            select(Transaction)
            .where(*predicates)
            .order_by(
                Transaction.transaction_date.desc(),
                Transaction.id.desc(),
            )
            .limit(limit + 1)
        )
        rows = tuple((await session.scalars(statement)).all())
        return TransactionSlice(
            items=rows[:limit],
            has_more=len(rows) > limit,
        )

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        values: TransactionValues,
        now: datetime,
    ) -> Transaction:
        """Add one complete user-owned ledger entry and flush it."""
        transaction = Transaction(
            id=uuid4(),
            user_id=user_id,
            account_id=values.account_id,
            category_id=values.category_id,
            import_job_id=values.import_job_id,
            transfer_group_id=values.transfer_group_id,
            transaction_type=values.transaction_type,
            amount=values.amount,
            transaction_date=values.transaction_date,
            description=values.description,
            merchant_name=values.merchant_name,
            source_type=values.source_type,
            external_source_hash=values.external_source_hash,
            status=values.status,
            is_user_modified=values.is_user_modified,
            created_at=now,
            updated_at=now,
        )
        session.add(transaction)
        await session.flush()
        return transaction

    async def replace(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction: Transaction,
        values: TransactionMutableValues,
        now: datetime,
        mark_user_modified: bool,
    ) -> Transaction:
        """Replace mutable fields while preserving ownership and provenance."""
        _require_owner(user_id=user_id, transaction=transaction)
        transaction.account_id = values.account_id
        transaction.category_id = values.category_id
        transaction.transaction_type = values.transaction_type
        transaction.amount = values.amount
        transaction.transaction_date = values.transaction_date
        transaction.description = values.description
        transaction.merchant_name = values.merchant_name
        transaction.is_user_modified = mark_user_modified
        transaction.updated_at = now
        await session.flush()
        return transaction

    async def delete(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction: Transaction,
    ) -> None:
        """Delete an entry already approved by the application service."""
        _require_owner(user_id=user_id, transaction=transaction)
        await session.delete(transaction)
        await session.flush()

    async def create_transfer_group(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        now: datetime,
    ) -> TransferGroup:
        """Add one owner-scoped transfer group and flush it."""
        group = TransferGroup(
            id=uuid4(),
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(group)
        await session.flush()
        return group


def _require_owner(
    *,
    user_id: UUID,
    transaction: Transaction,
) -> None:
    if transaction.user_id != user_id:
        raise ValueError(
            "Transaction does not belong to the specified user."
        )
