"""Application workflows for authenticated transaction management."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import (
    CategoryKind,
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.ledger import Transaction
from falcon_api.transactions.cursor import (
    InvalidTransactionCursorError,
    TransactionCursorCodec,
)
from falcon_api.transactions.repository import (
    TransactionCursor,
    TransactionFilters,
    TransactionMutableValues,
    TransactionRepository,
    TransactionValues,
)
from sqlalchemy.ext.asyncio import AsyncSession


_TRANSACTION_NOT_FOUND: Final = "transaction_not_found"
_ACCOUNT_NOT_FOUND: Final = "account_not_found"
_CATEGORY_NOT_FOUND: Final = "category_not_found"


@dataclass(frozen=True, slots=True)
class ManualTransactionCommand:
    """Validated public values for manual create or replacement."""

    account_id: UUID
    category_id: UUID | None
    transaction_type: TransactionType
    amount: Decimal
    transaction_date: date
    description: str
    merchant_name: str | None


@dataclass(frozen=True, slots=True)
class TransferCommand:
    """Validated public values for one internal transfer."""

    source_account_id: UUID
    destination_account_id: UUID
    amount: Decimal
    transaction_date: date
    description: str


@dataclass(frozen=True, slots=True)
class TransactionView:
    """Public transaction values with a positive amount magnitude."""

    id: UUID
    account_id: UUID
    category_id: UUID | None
    transaction_type: TransactionType
    amount: Decimal
    transaction_date: date
    description: str
    merchant_name: str | None
    source_type: TransactionSourceType
    status: TransactionStatus
    is_user_modified: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TransactionPage:
    """One public transaction page and its continuation token."""

    items: tuple[TransactionView, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class TransferResult:
    """Public paired entries created for one transfer group."""

    id: UUID
    debit: TransactionView
    credit: TransactionView


class TransactionService:
    """Own transaction authorization, mutation, and timeline policy."""

    def __init__(
        self,
        *,
        cursor_codec: TransactionCursorCodec,
        repository: TransactionRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or TransactionRepository()
        self._cursor_codec = cursor_codec
        self._clock = clock or SystemClock()

    async def create_manual(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        timezone: str,
        command: ManualTransactionCommand,
    ) -> TransactionView:
        """Create one posted manual income or expense."""
        self._validate_manual_command(command, timezone=timezone)
        await self._require_account(
            session,
            user_id=user_id,
            account_id=command.account_id,
        )
        await self._require_category(
            session,
            user_id=user_id,
            category_id=command.category_id,
            transaction_type=command.transaction_type,
        )
        transaction = await self._repository.create(
            session,
            user_id=user_id,
            values=_manual_create_values(command),
            now=self._clock.now(),
        )
        return _view(transaction)

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
    ) -> TransactionView:
        """Return one owned transaction or a uniform not-found error."""
        transaction = await self._repository.get_by_id(
            session,
            user_id=user_id,
            transaction_id=transaction_id,
        )
        if transaction is None:
            raise _not_found()
        return _view(transaction)

    async def list(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        filters: TransactionFilters,
        cursor_token: str | None,
        limit: int,
    ) -> TransactionPage:
        """Return a stable page with a bound continuation token."""
        cursor = self._decode_cursor(
            cursor_token,
            user_id=user_id,
            filters=filters,
        )
        result = await self._repository.list_by_user(
            session,
            user_id=user_id,
            filters=filters,
            cursor=cursor,
            limit=limit,
        )
        next_cursor = None
        if result.has_more and result.items:
            last = result.items[-1]
            next_cursor = self._cursor_codec.encode(
                user_id=user_id,
                filters=filters,
                cursor=TransactionCursor(
                    transaction_date=last.transaction_date,
                    transaction_id=last.id,
                ),
            )
        return TransactionPage(
            items=tuple(_view(item) for item in result.items),
            next_cursor=next_cursor,
        )

    async def replace_manual(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        timezone: str,
        transaction_id: UUID,
        command: ManualTransactionCommand,
    ) -> TransactionView:
        """Replace one eligible manual entry while preserving provenance."""
        self._validate_manual_command(command, timezone=timezone)
        transaction = await self._repository.get_by_id(
            session,
            user_id=user_id,
            transaction_id=transaction_id,
            for_update=True,
        )
        if transaction is None:
            raise _not_found()
        _require_manual_mutation(transaction)
        await self._require_account(
            session,
            user_id=user_id,
            account_id=command.account_id,
        )
        await self._require_category(
            session,
            user_id=user_id,
            category_id=command.category_id,
            transaction_type=command.transaction_type,
        )
        replaced = await self._repository.replace(
            session,
            user_id=user_id,
            transaction=transaction,
            values=_manual_mutable_values(command),
            now=self._clock.now(),
            mark_user_modified=True,
        )
        return _view(replaced)

    async def delete_manual(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
    ) -> None:
        """Delete one owned manual entry that is not a transfer."""
        transaction = await self._repository.get_by_id(
            session,
            user_id=user_id,
            transaction_id=transaction_id,
            for_update=True,
        )
        if transaction is None:
            raise _not_found()
        _require_manual_mutation(transaction)
        await self._repository.delete(
            session,
            user_id=user_id,
            transaction=transaction,
        )

    async def create_transfer(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        timezone: str,
        command: TransferCommand,
    ) -> TransferResult:
        """Create one transfer group and equal signed ledger entries."""
        _require_positive(command.amount)
        self._require_not_future(command.transaction_date, timezone=timezone)
        if command.source_account_id == command.destination_account_id:
            raise _validation_error(
                "transfer_accounts_same",
                "Source and destination accounts must be different.",
            )
        accounts: dict[UUID, Account] = {}
        for account_id in sorted(
            (
                command.source_account_id,
                command.destination_account_id,
            ),
            key=lambda value: value.int,
        ):
            accounts[account_id] = await self._require_account(
                session,
                user_id=user_id,
                account_id=account_id,
                for_update=True,
            )
        source = accounts[command.source_account_id]
        destination = accounts[command.destination_account_id]
        if source.currency != destination.currency:
            raise _validation_error(
                "transfer_currency_mismatch",
                "Transfer accounts must use the same currency.",
            )

        now = self._clock.now()
        group = await self._repository.create_transfer_group(
            session,
            user_id=user_id,
            now=now,
        )
        debit = await self._repository.create(
            session,
            user_id=user_id,
            values=_transfer_values(
                account_id=source.id,
                group_id=group.id,
                amount=-command.amount,
                command=command,
            ),
            now=now,
        )
        credit = await self._repository.create(
            session,
            user_id=user_id,
            values=_transfer_values(
                account_id=destination.id,
                group_id=group.id,
                amount=command.amount,
                command=command,
            ),
            now=now,
        )
        return TransferResult(
            id=group.id,
            debit=_view(debit),
            credit=_view(credit),
        )

    async def _require_account(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        account_id: UUID,
        for_update: bool = False,
    ) -> Account:
        account = await self._repository.get_active_account(
            session,
            user_id=user_id,
            account_id=account_id,
            for_update=for_update,
        )
        if account is None:
            raise ApplicationError(
                code=_ACCOUNT_NOT_FOUND,
                message="The account was not found.",
                status_code=404,
            )
        return account

    async def _require_category(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        category_id: UUID | None,
        transaction_type: TransactionType,
    ) -> Category | None:
        if category_id is None:
            return None
        category = await self._repository.get_active_category(
            session,
            user_id=user_id,
            category_id=category_id,
        )
        if category is None:
            raise ApplicationError(
                code=_CATEGORY_NOT_FOUND,
                message="The category was not found.",
                status_code=404,
            )
        expected = (
            CategoryKind.INCOME
            if transaction_type is TransactionType.INCOME
            else CategoryKind.EXPENSE
        )
        if category.kind != expected:
            raise _validation_error(
                "category_type_mismatch",
                "The category is incompatible with the transaction type.",
            )
        return category

    def _validate_manual_command(
        self,
        command: ManualTransactionCommand,
        *,
        timezone: str,
    ) -> None:
        if command.transaction_type not in {
            TransactionType.INCOME,
            TransactionType.EXPENSE,
        }:
            raise _validation_error(
                "manual_transaction_type_invalid",
                "Manual transactions must be income or expense.",
            )
        _require_positive(command.amount)
        self._require_not_future(command.transaction_date, timezone=timezone)

    def _require_not_future(
        self,
        transaction_date: date,
        *,
        timezone: str,
    ) -> None:
        try:
            local_today = self._clock.now().astimezone(
                ZoneInfo(timezone)
            ).date()
        except ZoneInfoNotFoundError as exc:
            raise ValueError("The trusted user timezone is invalid.") from exc
        if transaction_date > local_today:
            raise _validation_error(
                "future_transaction_date",
                "Posted transactions cannot use a future date.",
            )

    def _decode_cursor(
        self,
        token: str | None,
        *,
        user_id: UUID,
        filters: TransactionFilters,
    ) -> TransactionCursor | None:
        if token is None:
            return None
        try:
            return self._cursor_codec.decode(
                token,
                user_id=user_id,
                filters=filters,
            )
        except InvalidTransactionCursorError:
            raise _validation_error(
                "invalid_transaction_cursor",
                "The transaction cursor is invalid.",
            ) from None


def _manual_create_values(
    command: ManualTransactionCommand,
) -> TransactionValues:
    mutable = _manual_mutable_values(command)
    return TransactionValues(
        account_id=mutable.account_id,
        category_id=mutable.category_id,
        import_job_id=None,
        transfer_group_id=None,
        transaction_type=mutable.transaction_type,
        amount=mutable.amount,
        transaction_date=mutable.transaction_date,
        description=mutable.description,
        merchant_name=mutable.merchant_name,
        source_type=TransactionSourceType.MANUAL,
        external_source_hash=None,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
    )


def _manual_mutable_values(
    command: ManualTransactionCommand,
) -> TransactionMutableValues:
    signed_amount = (
        command.amount
        if command.transaction_type is TransactionType.INCOME
        else -command.amount
    )
    return TransactionMutableValues(
        account_id=command.account_id,
        category_id=command.category_id,
        transaction_type=command.transaction_type,
        amount=signed_amount,
        transaction_date=command.transaction_date,
        description=command.description,
        merchant_name=command.merchant_name,
    )


def _transfer_values(
    *,
    account_id: UUID,
    group_id: UUID,
    amount: Decimal,
    command: TransferCommand,
) -> TransactionValues:
    return TransactionValues(
        account_id=account_id,
        category_id=None,
        import_job_id=None,
        transfer_group_id=group_id,
        transaction_type=TransactionType.TRANSFER,
        amount=amount,
        transaction_date=command.transaction_date,
        description=command.description,
        merchant_name=None,
        source_type=TransactionSourceType.TRANSFER,
        external_source_hash=None,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
    )


def _view(transaction: Transaction) -> TransactionView:
    return TransactionView(
        id=transaction.id,
        account_id=transaction.account_id,
        category_id=transaction.category_id,
        transaction_type=transaction.transaction_type,
        amount=abs(transaction.amount),
        transaction_date=transaction.transaction_date,
        description=transaction.description,
        merchant_name=transaction.merchant_name,
        source_type=transaction.source_type,
        status=transaction.status,
        is_user_modified=transaction.is_user_modified,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


def _require_manual_mutation(transaction: Transaction) -> None:
    if (
        transaction.source_type is not TransactionSourceType.MANUAL
        or transaction.transaction_type
        not in {TransactionType.INCOME, TransactionType.EXPENSE}
        or transaction.transfer_group_id is not None
    ):
        raise ApplicationError(
            code="transaction_conflict",
            message="The transaction cannot be modified through this operation.",
            status_code=409,
        )


def _require_positive(amount: Decimal) -> None:
    if amount <= 0:
        raise _validation_error(
            "transaction_amount_invalid",
            "The transaction amount must be positive.",
        )


def _not_found() -> ApplicationError:
    return ApplicationError(
        code=_TRANSACTION_NOT_FOUND,
        message="The transaction was not found.",
        status_code=404,
    )


def _validation_error(code: str, message: str) -> ApplicationError:
    return ApplicationError(code=code, message=message, status_code=422)
