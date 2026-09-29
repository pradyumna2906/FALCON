"""Async session-factory and transaction-boundary tests."""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from falcon_api.core.errors import CommittedApplicationError
from falcon_api.infrastructure.persistence import (
    create_session_factory,
    transaction_scope,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


def test_session_factory_uses_managed_engine_and_safe_defaults() -> None:
    engine = cast(AsyncEngine, Mock())

    factory = create_session_factory(engine)

    assert factory.kw["bind"] is engine
    assert factory.kw["autoflush"] is False
    assert factory.kw["expire_on_commit"] is False


def _session_with_transaction() -> tuple[AsyncMock, AsyncMock]:
    transaction = AsyncMock()
    transaction.__aenter__.return_value = transaction
    transaction.__aexit__.return_value = False

    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=transaction)

    return session, transaction


def test_transaction_scope_commits_successful_work_and_closes() -> None:
    session, transaction = _session_with_transaction()
    factory = Mock(return_value=session)

    async def use_scope() -> None:
        async with transaction_scope(cast(Any, factory)) as yielded:
            assert yielded is session

    asyncio.run(use_scope())

    session.begin.assert_called_once_with()
    transaction.__aenter__.assert_awaited_once_with()
    transaction.__aexit__.assert_awaited_once_with(None, None, None)
    session.close.assert_awaited_once_with()


def test_transaction_scope_rolls_back_failed_work_and_closes() -> None:
    session, transaction = _session_with_transaction()
    factory = Mock(return_value=session)
    failure = RuntimeError("transaction failed")

    async def use_scope() -> None:
        async with transaction_scope(cast(Any, factory)):
            raise failure

    with pytest.raises(RuntimeError, match="transaction failed"):
        asyncio.run(use_scope())

    exit_args = transaction.__aexit__.await_args.args

    assert exit_args[0] is RuntimeError
    assert exit_args[1] is failure
    assert exit_args[2] is not None
    session.close.assert_awaited_once_with()


def test_transaction_scope_closes_when_transaction_entry_fails() -> None:
    transaction = AsyncMock()
    transaction.__aenter__.side_effect = RuntimeError("begin failed")

    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=transaction)
    factory = Mock(return_value=session)

    async def use_scope() -> None:
        async with transaction_scope(cast(Any, factory)):
            raise AssertionError("scope must not yield")

    with pytest.raises(RuntimeError, match="begin failed"):
        asyncio.run(use_scope())

    session.close.assert_awaited_once_with()

def test_transaction_scope_commits_marked_security_failure() -> None:
    session, transaction = _session_with_transaction()
    factory = Mock(return_value=session)
    failure = CommittedApplicationError(
        code="invalid_refresh_session",
        message="The refresh session is invalid or expired.",
        status_code=401,
    )

    async def use_scope() -> None:
        async with transaction_scope(cast(Any, factory)):
            raise failure

    with pytest.raises(CommittedApplicationError) as exc_info:
        asyncio.run(use_scope())

    assert exc_info.value is failure
    transaction.commit.assert_awaited_once_with()
    session.close.assert_awaited_once_with()
