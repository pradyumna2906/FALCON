"""Unit contracts for transaction application workflows."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from falcon_api.auth.clock import Clock
from falcon_api.core.errors import ApplicationError
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import (
    AccountType,
    CategoryKind,
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.ledger import Transaction, TransferGroup
from falcon_api.transactions import (
    ManualTransactionCommand,
    TransactionCursorCodec,
    TransactionFilters,
    TransactionRepository,
    TransactionService,
    TransactionSlice,
    TransferCommand,
)


_NOW = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
_SECRET = "transaction-service-test-secret-32-characters-minimum"


def _clock() -> Mock:
    clock = Mock(spec=Clock)
    clock.now.return_value = _NOW
    return clock


def _repository() -> AsyncMock:
    return AsyncMock(spec=TransactionRepository)


def _service(repository: AsyncMock) -> TransactionService:
    return TransactionService(
        repository=repository,
        cursor_codec=TransactionCursorCodec(signing_secret=_SECRET),
        clock=_clock(),
    )


def _account(user_id: UUID, *, currency: str = "INR") -> Account:
    return Account(
        id=uuid4(),
        user_id=user_id,
        name=f"Account {uuid4().hex}",
        account_type=AccountType.BANK,
        institution_name=None,
        masked_reference=None,
        currency=currency,
        opening_balance=Decimal("0"),
        opening_balance_date=date(2026, 8, 1),
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _category(
    user_id: UUID,
    *,
    kind: CategoryKind,
) -> Category:
    return Category(
        id=uuid4(),
        user_id=user_id,
        name=kind.value.title(),
        normalized_name=f"{kind.value}-{uuid4().hex}",
        kind=kind,
        parent_id=None,
        is_system=False,
        display_order=0,
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _transaction(
    user_id: UUID,
    *,
    transaction_type: TransactionType = TransactionType.EXPENSE,
    source_type: TransactionSourceType = TransactionSourceType.MANUAL,
    amount: Decimal = Decimal("-1250.5000"),
    transfer_group_id: UUID | None = None,
) -> Transaction:
    return Transaction(
        id=uuid4(),
        user_id=user_id,
        account_id=uuid4(),
        category_id=None,
        import_job_id=None,
        transfer_group_id=transfer_group_id,
        transaction_type=transaction_type,
        amount=amount,
        transaction_date=date(2026, 8, 20),
        description="Monthly groceries",
        merchant_name="Local Market",
        source_type=source_type,
        external_source_hash=None,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _command(
    *,
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    transaction_type: TransactionType = TransactionType.EXPENSE,
    amount: Decimal = Decimal("1250.5000"),
    transaction_date: date = date(2026, 8, 20),
) -> ManualTransactionCommand:
    return ManualTransactionCommand(
        account_id=account_id or uuid4(),
        category_id=category_id,
        transaction_type=transaction_type,
        amount=amount,
        transaction_date=transaction_date,
        description="Monthly groceries",
        merchant_name="Local Market",
    )


def test_create_manual_expense_authorizes_and_signs_ledger_amount() -> None:
    user_id = uuid4()
    command = _command(category_id=uuid4())
    repository = _repository()
    repository.get_active_account.return_value = _account(user_id)
    repository.get_active_category.return_value = _category(
        user_id,
        kind=CategoryKind.EXPENSE,
    )
    repository.create.return_value = _transaction(user_id)

    result = asyncio.run(
        _service(repository).create_manual(
            Mock(),
            user_id=user_id,
            timezone="Asia/Kolkata",
            command=command,
        )
    )

    values = repository.create.await_args.kwargs["values"]
    assert values.amount == Decimal("-1250.5000")
    assert values.source_type is TransactionSourceType.MANUAL
    assert values.status is TransactionStatus.POSTED
    assert result.amount == Decimal("1250.5000")


def test_create_manual_income_skips_optional_category() -> None:
    user_id = uuid4()
    repository = _repository()
    repository.get_active_account.return_value = _account(user_id)
    repository.create.return_value = _transaction(
        user_id,
        transaction_type=TransactionType.INCOME,
        amount=Decimal("5000"),
    )

    asyncio.run(
        _service(repository).create_manual(
            Mock(),
            user_id=user_id,
            timezone="UTC",
            command=_command(
                transaction_type=TransactionType.INCOME,
                amount=Decimal("5000"),
            ),
        )
    )

    values = repository.create.await_args.kwargs["values"]
    assert values.amount == Decimal("5000")
    repository.get_active_category.assert_not_awaited()


@pytest.mark.parametrize(
    ("command", "code"),
    [
        (_command(amount=Decimal("0")), "transaction_amount_invalid"),
        (
            _command(transaction_type=TransactionType.ADJUSTMENT),
            "manual_transaction_type_invalid",
        ),
        (
            _command(transaction_date=date(2026, 8, 22)),
            "future_transaction_date",
        ),
    ],
)
def test_create_manual_rejects_invalid_business_values(
    command: ManualTransactionCommand,
    code: str,
) -> None:
    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(_repository()).create_manual(
                Mock(),
                user_id=uuid4(),
                timezone="Asia/Kolkata",
                command=command,
            )
        )

    assert info.value.code == code


def test_create_manual_rejects_missing_account() -> None:
    repository = _repository()
    repository.get_active_account.return_value = None

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).create_manual(
                Mock(),
                user_id=uuid4(),
                timezone="UTC",
                command=_command(),
            )
        )

    assert info.value.code == "account_not_found"
    assert info.value.status_code == 404


@pytest.mark.parametrize(
    ("category", "code"),
    [
        (None, "category_not_found"),
        ("income", "category_type_mismatch"),
    ],
)
def test_create_manual_rejects_missing_or_mismatched_category(
    category: str | None,
    code: str,
) -> None:
    user_id = uuid4()
    repository = _repository()
    repository.get_active_account.return_value = _account(user_id)
    repository.get_active_category.return_value = (
        None
        if category is None
        else _category(user_id, kind=CategoryKind.INCOME)
    )

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).create_manual(
                Mock(),
                user_id=user_id,
                timezone="UTC",
                command=_command(category_id=uuid4()),
            )
        )

    assert info.value.code == code


def test_get_returns_positive_public_view_or_not_found() -> None:
    user_id = uuid4()
    repository = _repository()
    repository.get_by_id.return_value = _transaction(user_id)

    result = asyncio.run(
        _service(repository).get(
            Mock(), user_id=user_id, transaction_id=uuid4()
        )
    )

    assert result.amount == Decimal("1250.5000")

    repository.get_by_id.return_value = None
    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).get(
                Mock(), user_id=user_id, transaction_id=uuid4()
            )
        )
    assert info.value.code == "transaction_not_found"


def test_list_returns_bound_next_cursor_and_accepts_it() -> None:
    user_id = uuid4()
    filters = TransactionFilters(account_id=uuid4())
    rows = (_transaction(user_id), _transaction(user_id))
    repository = _repository()
    repository.list_by_user.return_value = TransactionSlice(rows, True)
    service = _service(repository)

    first = asyncio.run(
        service.list(
            Mock(),
            user_id=user_id,
            filters=filters,
            cursor_token=None,
            limit=2,
        )
    )
    assert first.next_cursor is not None
    assert len(first.items) == 2

    repository.list_by_user.return_value = TransactionSlice((), False)
    second = asyncio.run(
        service.list(
            Mock(),
            user_id=user_id,
            filters=filters,
            cursor_token=first.next_cursor,
            limit=2,
        )
    )
    cursor = repository.list_by_user.await_args.kwargs["cursor"]
    assert cursor.transaction_date == rows[-1].transaction_date
    assert cursor.transaction_id == rows[-1].id
    assert second.next_cursor is None


def test_list_rejects_invalid_cursor_with_public_error() -> None:
    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(_repository()).list(
                Mock(),
                user_id=uuid4(),
                filters=TransactionFilters(),
                cursor_token="invalid.cursor",
                limit=50,
            )
        )

    assert info.value.code == "invalid_transaction_cursor"
    assert info.value.status_code == 422


def test_replace_manual_locks_authorizes_and_preserves_provenance() -> None:
    user_id = uuid4()
    transaction = _transaction(user_id)
    repository = _repository()
    repository.get_by_id.return_value = transaction
    repository.get_active_account.return_value = _account(user_id)
    repository.replace.return_value = transaction

    result = asyncio.run(
        _service(repository).replace_manual(
            Mock(),
            user_id=user_id,
            timezone="UTC",
            transaction_id=transaction.id,
            command=_command(),
        )
    )

    assert repository.get_by_id.await_args.kwargs["for_update"] is True
    assert repository.replace.await_args.kwargs["mark_user_modified"] is True
    assert result.id == transaction.id


@pytest.mark.parametrize(
    "transaction",
    [
        None,
        _transaction(uuid4(), source_type=TransactionSourceType.IMPORT),
        _transaction(
            uuid4(),
            transaction_type=TransactionType.TRANSFER,
            source_type=TransactionSourceType.TRANSFER,
            transfer_group_id=uuid4(),
        ),
    ],
)
def test_replace_rejects_missing_or_immutable_entries(
    transaction: Transaction | None,
) -> None:
    repository = _repository()
    repository.get_by_id.return_value = transaction

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).replace_manual(
                Mock(),
                user_id=uuid4(),
                timezone="UTC",
                transaction_id=uuid4(),
                command=_command(),
            )
        )

    assert info.value.code in {
        "transaction_not_found",
        "transaction_conflict",
    }


def test_delete_manual_locks_and_deletes_eligible_entry() -> None:
    user_id = uuid4()
    transaction = _transaction(user_id)
    repository = _repository()
    repository.get_by_id.return_value = transaction

    asyncio.run(
        _service(repository).delete_manual(
            Mock(), user_id=user_id, transaction_id=transaction.id
        )
    )

    repository.delete.assert_awaited_once()
    assert repository.get_by_id.await_args.kwargs["for_update"] is True


def test_delete_rejects_missing_entry() -> None:
    repository = _repository()
    repository.get_by_id.return_value = None

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).delete_manual(
                Mock(), user_id=uuid4(), transaction_id=uuid4()
            )
        )
    assert info.value.code == "transaction_not_found"


def test_create_transfer_locks_accounts_and_creates_equal_pair() -> None:
    user_id = uuid4()
    source = _account(user_id)
    destination = _account(user_id)
    group = TransferGroup(
        id=uuid4(),
        user_id=user_id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    debit = _transaction(
        user_id,
        transaction_type=TransactionType.TRANSFER,
        source_type=TransactionSourceType.TRANSFER,
        amount=Decimal("-500"),
        transfer_group_id=group.id,
    )
    credit = _transaction(
        user_id,
        transaction_type=TransactionType.TRANSFER,
        source_type=TransactionSourceType.TRANSFER,
        amount=Decimal("500"),
        transfer_group_id=group.id,
    )
    repository = _repository()
    accounts = {source.id: source, destination.id: destination}

    async def get_account(*_args, **kwargs):
        return accounts[kwargs["account_id"]]

    repository.get_active_account.side_effect = get_account
    repository.create_transfer_group.return_value = group
    repository.create.side_effect = [debit, credit]

    result = asyncio.run(
        _service(repository).create_transfer(
            Mock(),
            user_id=user_id,
            timezone="UTC",
            command=TransferCommand(
                source_account_id=source.id,
                destination_account_id=destination.id,
                amount=Decimal("500"),
                transaction_date=date(2026, 8, 20),
                description="Move to savings",
            ),
        )
    )

    assert result.id == group.id
    assert result.debit.amount == result.credit.amount == Decimal("500")
    calls = repository.get_active_account.await_args_list
    assert all(call.kwargs["for_update"] is True for call in calls)
    locked_ids = [call.kwargs["account_id"] for call in calls]
    assert locked_ids == sorted(locked_ids, key=lambda value: value.int)
    values = [call.kwargs["values"] for call in repository.create.await_args_list]
    assert values[0].amount == Decimal("-500")
    assert values[1].amount == Decimal("500")


@pytest.mark.parametrize(
    ("amount", "same_account", "code"),
    [
        (Decimal("0"), False, "transaction_amount_invalid"),
        (Decimal("500"), True, "transfer_accounts_same"),
    ],
)
def test_transfer_rejects_invalid_amount_or_same_account(
    amount: Decimal,
    same_account: bool,
    code: str,
) -> None:
    source_id = uuid4()
    destination_id = source_id if same_account else uuid4()

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(_repository()).create_transfer(
                Mock(),
                user_id=uuid4(),
                timezone="UTC",
                command=TransferCommand(
                    source_account_id=source_id,
                    destination_account_id=destination_id,
                    amount=amount,
                    transaction_date=date(2026, 8, 20),
                    description="Move funds",
                ),
            )
        )
    assert info.value.code == code


def test_transfer_rejects_missing_or_currency_mismatched_accounts() -> None:
    user_id = uuid4()
    repository = _repository()
    source = _account(user_id, currency="INR")
    destination = _account(user_id, currency="USD")
    command = TransferCommand(
        source_account_id=source.id,
        destination_account_id=destination.id,
        amount=Decimal("500"),
        transaction_date=date(2026, 8, 20),
        description="Move funds",
    )
    accounts = {source.id: source, destination.id: destination}

    async def get_account(*_args, **kwargs):
        return accounts[kwargs["account_id"]]

    repository.get_active_account.side_effect = get_account

    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).create_transfer(
                Mock(), user_id=user_id, timezone="UTC", command=command
            )
        )
    assert info.value.code == "transfer_currency_mismatch"

    repository.get_active_account.side_effect = None
    repository.get_active_account.return_value = None
    with pytest.raises(ApplicationError) as info:
        asyncio.run(
            _service(repository).create_transfer(
                Mock(), user_id=user_id, timezone="UTC", command=command
            )
        )
    assert info.value.code == "account_not_found"


def test_trusted_timezone_must_be_valid() -> None:
    with pytest.raises(ValueError, match="trusted user timezone"):
        asyncio.run(
            _service(_repository()).create_manual(
                Mock(),
                user_id=uuid4(),
                timezone="Invalid/Timezone",
                command=_command(),
            )
        )
