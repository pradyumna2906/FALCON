"""PostgreSQL resource, session and readiness tests."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from falcon_api.core.config import Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import (
    DatabaseResources,
    assert_database_ready,
    create_database_resources,
    get_database_session,
    session_scope,
)
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _resources_with(
    *,
    engine: object,
    session_factory: object | None = None,
) -> DatabaseResources:
    return DatabaseResources(
        engine=cast(AsyncEngine, engine),
        session_factory=cast(
            async_sessionmaker[AsyncSession],
            session_factory or Mock(),
        ),
    )


def test_resources_use_async_psycopg_and_safe_engine_configuration(
    test_settings: Settings,
) -> None:
    resources = create_database_resources(test_settings)

    assert resources.engine.url.drivername == "postgresql+psycopg"
    assert resources.engine.sync_engine.hide_parameters is True
    assert resources.engine.sync_engine.pool.size() == test_settings.db_pool_size
    assert "test-only-database-password" not in str(resources.engine.url)

    asyncio.run(resources.dispose())


def test_session_scope_closes_without_implicit_commit() -> None:
    session = AsyncMock(spec=AsyncSession)
    resources = _resources_with(
        engine=Mock(),
        session_factory=Mock(return_value=session),
    )

    async def use_session() -> None:
        async with session_scope(resources) as yielded:
            assert yielded is session

    asyncio.run(use_session())

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once_with()


def test_session_scope_rolls_back_and_closes_failed_work() -> None:
    session = AsyncMock(spec=AsyncSession)
    resources = _resources_with(
        engine=Mock(),
        session_factory=Mock(return_value=session),
    )

    async def fail_session() -> None:
        async with session_scope(resources):
            raise RuntimeError("unit-of-work failed")

    with pytest.raises(RuntimeError, match="unit-of-work failed"):
        asyncio.run(fail_session())

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()


def test_request_dependency_uses_attached_process_resources() -> None:
    session = AsyncMock(spec=AsyncSession)
    resources = _resources_with(
        engine=Mock(),
        session_factory=Mock(return_value=session),
    )
    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(database=resources),
            ),
        ),
    )

    async def consume_dependency() -> None:
        dependency = get_database_session(request)
        assert await anext(dependency) is session
        with pytest.raises(StopAsyncIteration):
            await anext(dependency)

    asyncio.run(consume_dependency())

    session.close.assert_awaited_once_with()


class _SuccessfulConnection:
    def __init__(self) -> None:
        self.executed_statement: str | None = None

    async def execute(self, statement: object) -> None:
        self.executed_statement = str(statement)


class _ConnectionContext:
    def __init__(self, connection: _SuccessfulConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _SuccessfulConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


class _SuccessfulEngine:
    def __init__(self) -> None:
        self.connection = _SuccessfulConnection()
        self.connect_calls = 0

    def connect(self) -> _ConnectionContext:
        self.connect_calls += 1
        return _ConnectionContext(self.connection)


class _FailingEngine:
    def connect(self) -> None:
        raise RuntimeError("database-password=TOP-SECRET")


class _BlockingConnectionContext:
    async def __aenter__(self) -> None:
        await asyncio.Event().wait()

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


class _BlockingEngine:
    def connect(self) -> _BlockingConnectionContext:
        return _BlockingConnectionContext()


def test_readiness_executes_exact_bounded_probe() -> None:
    engine = _SuccessfulEngine()
    resources = _resources_with(engine=engine)

    asyncio.run(assert_database_ready(resources, timeout_seconds=0.1))

    assert engine.connect_calls == 1
    assert engine.connection.executed_statement == "SELECT 1"


@pytest.mark.parametrize("engine", [_FailingEngine(), _BlockingEngine()])
def test_readiness_failure_has_fixed_safe_contract(engine: object) -> None:
    resources = _resources_with(engine=engine)

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(assert_database_ready(resources, timeout_seconds=0.01))

    error = exc_info.value
    assert error.status_code == 503
    assert error.code == "service_unavailable"
    assert error.public_message == "The service is temporarily unavailable."
    assert "TOP-SECRET" not in str(error)
