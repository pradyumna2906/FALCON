"""Unit contracts for user-scoped transaction persistence."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from falcon_api.models.enums import (
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.ledger import Transaction
from falcon_api.transactions import (
    TransactionCursor,
    TransactionFilters,
    TransactionMutableValues,
    TransactionRepository,
    TransactionValues,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession


_NOW = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    return session


def _values() -> TransactionValues:
    return TransactionValues(
        account_id=uuid4(),
        category_id=uuid4(),
        import_job_id=None,
        transfer_group_id=None,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("-1250.5000"),
        transaction_date=date(2026, 8, 20),
        description="Monthly groceries",
        merchant_name="Local Market",
        source_type=TransactionSourceType.MANUAL,
        external_source_hash=None,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
    )


def _mutable_values() -> TransactionMutableValues:
    return TransactionMutableValues(
        account_id=uuid4(),
        category_id=None,
        transaction_type=TransactionType.INCOME,
        amount=Decimal("5000.0000"),
        transaction_date=date(2026, 8, 19),
        description="Consulting income",
        merchant_name=None,
    )


def _transaction(user_id: UUID, *, days_ago: int = 0) -> Transaction:
    return Transaction(
        id=uuid4(),
        user_id=user_id,
        account_id=uuid4(),
        category_id=None,
        import_job_id=None,
        transfer_group_id=None,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("-100.0000"),
        transaction_date=date(2026, 8, 20) - timedelta(days=days_ago),
        description="Test transaction",
        merchant_name=None,
        source_type=TransactionSourceType.MANUAL,
        external_source_hash=None,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _compiled_scalar(session: AsyncMock) -> tuple[str, dict[str, object]]:
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_get_active_account_is_owner_scoped_and_excludes_archived() -> None:
    session = _session()
    user_id = uuid4()
    account_id = uuid4()

    asyncio.run(
        TransactionRepository().get_active_account(
            session,
            user_id=user_id,
            account_id=account_id,
            for_update=True,
        )
    )

    query, params = _compiled_scalar(session)
    assert "accounts.user_id =" in query
    assert "accounts.id =" in query
    assert "accounts.archived_at IS NULL" in query
    assert "FOR UPDATE" in query
    assert user_id in params.values()
    assert account_id in params.values()


def test_get_active_account_does_not_lock_by_default() -> None:
    session = _session()

    asyncio.run(
        TransactionRepository().get_active_account(
            session,
            user_id=uuid4(),
            account_id=uuid4(),
        )
    )

    query, _ = _compiled_scalar(session)
    assert "FOR UPDATE" not in query


def test_get_active_category_allows_only_system_or_same_user() -> None:
    session = _session()
    user_id = uuid4()
    category_id = uuid4()

    asyncio.run(
        TransactionRepository().get_active_category(
            session,
            user_id=user_id,
            category_id=category_id,
        )
    )

    query, params = _compiled_scalar(session)
    assert "categories.id =" in query
    assert "categories.archived_at IS NULL" in query
    assert "categories.is_system IS true" in query
    assert "categories.user_id IS NULL" in query
    assert "categories.is_system IS false" in query
    assert "categories.user_id =" in query
    assert user_id in params.values()
    assert category_id in params.values()


def test_get_transaction_is_owner_scoped_and_lockable() -> None:
    session = _session()
    user_id = uuid4()
    transaction_id = uuid4()

    asyncio.run(
        TransactionRepository().get_by_id(
            session,
            user_id=user_id,
            transaction_id=transaction_id,
            for_update=True,
        )
    )

    query, params = _compiled_scalar(session)
    assert "transactions.user_id =" in query
    assert "transactions.id =" in query
    assert "FOR UPDATE" in query
    assert user_id in params.values()
    assert transaction_id in params.values()


def test_get_transaction_does_not_lock_by_default() -> None:
    session = _session()

    asyncio.run(
        TransactionRepository().get_by_id(
            session,
            user_id=uuid4(),
            transaction_id=uuid4(),
        )
    )

    query, _ = _compiled_scalar(session)
    assert "FOR UPDATE" not in query


def test_list_applies_all_filters_cursor_order_and_bounded_lookahead() -> None:
    session = _session()
    scalar_result = Mock()
    user_id = uuid4()
    rows = tuple(_transaction(user_id, days_ago=value) for value in range(3))
    scalar_result.all.return_value = list(rows)
    session.scalars.return_value = scalar_result
    filters = TransactionFilters(
        account_id=uuid4(),
        category_id=uuid4(),
        transaction_type=TransactionType.EXPENSE,
        status=TransactionStatus.POSTED,
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 20),
    )
    cursor = TransactionCursor(
        transaction_date=date(2026, 8, 18),
        transaction_id=uuid4(),
    )

    result = asyncio.run(
        TransactionRepository().list_by_user(
            session,
            user_id=user_id,
            filters=filters,
            cursor=cursor,
            limit=2,
        )
    )

    statement = session.scalars.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    query = str(compiled)
    assert "transactions.user_id =" in query
    assert "transactions.account_id =" in query
    assert "transactions.category_id =" in query
    assert "transactions.transaction_type =" in query
    assert "transactions.status =" in query
    assert "transactions.transaction_date >=" in query
    assert "transactions.transaction_date <=" in query
    assert "transactions.transaction_date <" in query
    assert "transactions.id <" in query
    assert "transactions.transaction_date DESC" in query
    assert "transactions.id DESC" in query
    assert compiled.params["param_1"] == 3
    assert result.items == rows[:2]
    assert result.has_more is True


def test_list_without_lookahead_reports_no_more_rows() -> None:
    session = _session()
    scalar_result = Mock()
    row = _transaction(uuid4())
    scalar_result.all.return_value = [row]
    session.scalars.return_value = scalar_result

    result = asyncio.run(
        TransactionRepository().list_by_user(
            session,
            user_id=row.user_id,
            filters=TransactionFilters(),
            cursor=None,
            limit=50,
        )
    )

    assert result.items == (row,)
    assert result.has_more is False


def test_create_maps_complete_values_and_flushes() -> None:
    session = _session()
    user_id = uuid4()
    values = _values()

    transaction = asyncio.run(
        TransactionRepository().create(
            session,
            user_id=user_id,
            values=values,
            now=_NOW,
        )
    )

    assert transaction.user_id == user_id
    assert transaction.account_id == values.account_id
    assert transaction.category_id == values.category_id
    assert transaction.transaction_type is TransactionType.EXPENSE
    assert transaction.amount == Decimal("-1250.5000")
    assert transaction.source_type is TransactionSourceType.MANUAL
    assert transaction.status is TransactionStatus.POSTED
    assert transaction.created_at == _NOW
    assert transaction.updated_at == _NOW
    session.add.assert_called_once_with(transaction)
    session.flush.assert_awaited_once_with()


def test_replace_preserves_identity_owner_and_provenance() -> None:
    session = _session()
    user_id = uuid4()
    transaction = _transaction(user_id)
    identity = transaction.id
    created_at = transaction.created_at
    source_type = transaction.source_type

    result = asyncio.run(
        TransactionRepository().replace(
            session,
            user_id=user_id,
            transaction=transaction,
            values=_mutable_values(),
            now=_NOW + timedelta(hours=1),
            mark_user_modified=True,
        )
    )

    assert result is transaction
    assert transaction.id == identity
    assert transaction.user_id == user_id
    assert transaction.created_at == created_at
    assert transaction.source_type is source_type
    assert transaction.transaction_type is TransactionType.INCOME
    assert transaction.amount == Decimal("5000.0000")
    assert transaction.is_user_modified is True
    session.flush.assert_awaited_once_with()


def test_replace_rejects_cross_user_transaction() -> None:
    session = _session()

    with pytest.raises(ValueError, match="does not belong"):
        asyncio.run(
            TransactionRepository().replace(
                session,
                user_id=uuid4(),
                transaction=_transaction(uuid4()),
                values=_mutable_values(),
                now=_NOW,
                mark_user_modified=True,
            )
        )

    session.flush.assert_not_awaited()


def test_delete_rejects_cross_user_transaction() -> None:
    session = _session()

    with pytest.raises(ValueError, match="does not belong"):
        asyncio.run(
            TransactionRepository().delete(
                session,
                user_id=uuid4(),
                transaction=_transaction(uuid4()),
            )
        )

    session.delete.assert_not_awaited()


def test_delete_owned_transaction_flushes_without_committing() -> None:
    session = _session()
    transaction = _transaction(uuid4())

    asyncio.run(
        TransactionRepository().delete(
            session,
            user_id=transaction.user_id,
            transaction=transaction,
        )
    )

    session.delete.assert_awaited_once_with(transaction)
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


def test_create_transfer_group_is_user_owned_and_never_commits() -> None:
    session = _session()
    user_id = uuid4()

    group = asyncio.run(
        TransactionRepository().create_transfer_group(
            session,
            user_id=user_id,
            now=_NOW,
        )
    )

    assert group.user_id == user_id
    assert group.created_at == _NOW
    assert group.updated_at == _NOW
    session.add.assert_called_once_with(group)
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()
