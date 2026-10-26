"""PostgreSQL resource, request-session and readiness tests."""

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
)
from falcon_api.infrastructure.persistence import SessionFactory
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


def _resources_with(
    *,
    engine: object,
    session_factory: object | None = None,
) -> DatabaseResources:
    return DatabaseResources(
        engine=cast(AsyncEngine, engine),
        session_factory=cast(
            SessionFactory,
            session_factory or Mock(),
        ),
    )


def _session_with_transaction() -> tuple[AsyncMock, AsyncMock]:
    transaction = AsyncMock()
    transaction.__aenter__.return_value = transaction
    transaction.__aexit__.return_value = False

    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=transaction)

    return session, transaction


def test_resources_use_async_psycopg_and_safe_engine_configuration(
    test_settings: Settings,
) -> None:
    resources = create_database_resources(test_settings)

    assert resources.engine.url.drivername == "postgresql+psycopg"
    assert resources.engine.sync_engine.hide_parameters is True
    assert resources.engine.sync_engine.pool.size() == test_settings.db_pool_size
    assert resources.session_factory.kw["bind"] is resources.engine
    assert resources.session_factory.kw["autoflush"] is False
    assert resources.session_factory.kw["expire_on_commit"] is False
    assert "test-only-database-password" not in str(resources.engine.url)

    asyncio.run(resources.dispose())


def test_request_dependency_commits_successful_work_and_closes() -> None:
    session, transaction = _session_with_transaction()
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

    session.begin.assert_called_once_with()
    transaction.__aenter__.assert_awaited_once_with()
    transaction.__aexit__.assert_awaited_once_with(None, None, None)
    session.close.assert_awaited_once_with()


def test_request_dependency_rolls_back_failed_work_and_closes() -> None:
    session, transaction = _session_with_transaction()
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
    failure = RuntimeError("request operation failed")

    async def fail_dependency() -> None:
        dependency = get_database_session(request)

        assert await anext(dependency) is session
        await dependency.athrow(failure)

    with pytest.raises(RuntimeError, match="request operation failed"):
        asyncio.run(fail_dependency())

    exit_args = transaction.__aexit__.await_args.args

    assert exit_args[0] is RuntimeError
    assert exit_args[1] is failure
    assert exit_args[2] is not None
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
