"""Application-service tests for ledger setup resources."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.core.errors import ApplicationError
from falcon_api.ledger import AccountCreateCommand, LedgerRepository, LedgerService
from falcon_api.models.enums import AccountType
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


_NOW = datetime(2026, 8, 20, 16, 30, tzinfo=UTC)


class FixedClock:
    """Return one deterministic application timestamp."""

    def now(self) -> datetime:
        return _NOW


class NestedContext:
    """Minimal async savepoint context for service unit tests."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.begin_nested = Mock(return_value=NestedContext())
    return session


def _command(*, currency: str | None = None) -> AccountCreateCommand:
    return AccountCreateCommand(
        name="Primary Bank",
        account_type=AccountType.BANK,
        institution_name="State Bank",
        masked_reference=None,
        currency=currency,
        opening_balance=Decimal("25000.0000"),
        opening_balance_date=date(2026, 8, 20),
    )


def _integrity_error(constraint_name: str) -> IntegrityError:
    original = Exception("safe test error")
    original.diag = SimpleNamespace(constraint_name=constraint_name)
    return IntegrityError("statement", {}, original)


def test_create_account_uses_principal_default_currency() -> None:
    user_id = uuid4()
    account = Mock()
    repository = AsyncMock(spec=LedgerRepository)
    repository.create_account.return_value = account
    service = LedgerService(repository=repository, clock=FixedClock())
    session = _session()

    result = asyncio.run(
        service.create_account(
            session,
            user_id=user_id,
            default_currency="INR",
            command=_command(),
        )
    )

    assert result is account
    call = repository.create_account.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == user_id
    assert call.kwargs["values"].currency == "INR"
    assert call.kwargs["now"] == _NOW


def test_create_account_honors_explicit_currency() -> None:
    repository = AsyncMock(spec=LedgerRepository)
    repository.create_account.return_value = Mock()
    service = LedgerService(repository=repository, clock=FixedClock())

    asyncio.run(
        service.create_account(
            _session(),
            user_id=uuid4(),
            default_currency="INR",
            command=_command(currency="USD"),
        )
    )

    assert repository.create_account.await_args.kwargs["values"].currency == "USD"


def test_create_account_maps_only_known_name_conflict() -> None:
    repository = AsyncMock(spec=LedgerRepository)
    repository.create_account.side_effect = _integrity_error(
        "uq_accounts_user_name"
    )
    service = LedgerService(repository=repository, clock=FixedClock())

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.create_account(
                _session(),
                user_id=uuid4(),
                default_currency="INR",
                command=_command(),
            )
        )

    assert captured.value.code == "account_name_conflict"
    assert captured.value.status_code == 409


def test_create_account_reraises_unknown_integrity_error() -> None:
    repository = AsyncMock(spec=LedgerRepository)
    error = _integrity_error("other_constraint")
    repository.create_account.side_effect = error
    service = LedgerService(repository=repository, clock=FixedClock())

    with pytest.raises(IntegrityError) as captured:
        asyncio.run(
            service.create_account(
                _session(),
                user_id=uuid4(),
                default_currency="INR",
                command=_command(),
            )
        )

    assert captured.value is error


def test_lists_delegate_with_trusted_user_scope() -> None:
    user_id = uuid4()
    repository = AsyncMock(spec=LedgerRepository)
    repository.list_accounts.return_value = (Mock(),)
    repository.list_categories.return_value = (Mock(), Mock())
    service = LedgerService(repository=repository)
    session = _session()

    accounts = asyncio.run(service.list_accounts(session, user_id=user_id))
    categories = asyncio.run(service.list_categories(session, user_id=user_id))

    assert len(accounts) == 1
    assert len(categories) == 2
    repository.list_accounts.assert_awaited_once_with(
        session, user_id=user_id
    )
    repository.list_categories.assert_awaited_once_with(
        session, user_id=user_id
    )
