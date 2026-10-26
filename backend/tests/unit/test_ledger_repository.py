"""Unit contracts for user-scoped ledger setup persistence."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from falcon_api.ledger import AccountValues, LedgerRepository
from falcon_api.models.enums import AccountType
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession


_NOW = datetime(2026, 8, 20, 16, 0, tzinfo=UTC)


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    return session


def _values() -> AccountValues:
    return AccountValues(
        name="Primary Bank",
        account_type=AccountType.BANK,
        institution_name="State Bank",
        masked_reference="•••• 1234",
        currency="INR",
        opening_balance=Decimal("25000.0000"),
        opening_balance_date=date(2026, 8, 20),
    )


def _compiled_scalars_query(session: AsyncMock) -> tuple[str, dict[str, object]]:
    statement = session.scalars.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_create_account_sets_owner_and_complete_values() -> None:
    user_id = uuid4()
    session = _session()

    account = asyncio.run(
        LedgerRepository().create_account(
            session,
            user_id=user_id,
            values=_values(),
            now=_NOW,
        )
    )

    assert account.user_id == user_id
    assert account.name == "Primary Bank"
    assert account.account_type is AccountType.BANK
    assert account.currency == "INR"
    assert account.archived_at is None
    assert account.created_at == _NOW
    session.add.assert_called_once_with(account)
    session.flush.assert_awaited_once_with()


def test_list_accounts_is_owned_active_and_deterministic() -> None:
    user_id = uuid4()
    session = _session()
    expected = (Mock(), Mock())
    scalar_result = Mock()
    scalar_result.all.return_value = list(expected)
    session.scalars.return_value = scalar_result

    result = asyncio.run(
        LedgerRepository().list_accounts(session, user_id=user_id)
    )

    query, params = _compiled_scalars_query(session)
    assert result == expected
    assert "accounts.user_id =" in query
    assert "accounts.archived_at IS NULL" in query
    assert "ORDER BY accounts.created_at ASC, accounts.id ASC" in query
    assert user_id in params.values()


def test_list_categories_allows_only_system_or_owned_active_rows() -> None:
    user_id = uuid4()
    session = _session()
    scalar_result = Mock()
    scalar_result.all.return_value = []
    session.scalars.return_value = scalar_result

    result = asyncio.run(
        LedgerRepository().list_categories(session, user_id=user_id)
    )

    query, params = _compiled_scalars_query(session)
    assert result == ()
    assert "categories.archived_at IS NULL" in query
    assert "categories.is_system IS true" in query
    assert "categories.user_id =" in query
    assert "categories.display_order ASC" in query
    assert user_id in params.values()
