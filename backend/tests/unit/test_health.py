"""Initial API endpoint tests."""

from typing import cast
from unittest.mock import Mock

from falcon_api.core.config import Settings
from falcon_api.infrastructure.database import DatabaseResources
from falcon_api.main import DatabaseFactory, create_app
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


class _ReadyConnection:
    def __init__(self) -> None:
        self.execute_calls = 0

    async def execute(self, statement: object) -> None:
        assert str(statement) == "SELECT 1"
        self.execute_calls += 1


class _ReadyContext:
    def __init__(self, connection: _ReadyConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _ReadyConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


class _ReadyEngine:
    def __init__(self) -> None:
        self.connection = _ReadyConnection()
        self.connect_calls = 0
        self.dispose_calls = 0

    def connect(self) -> _ReadyContext:
        self.connect_calls += 1
        return _ReadyContext(self.connection)

    async def dispose(self) -> None:
        self.dispose_calls += 1


class _UnavailableEngine:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.dispose_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        raise RuntimeError("database-password=TOP-SECRET")

    async def dispose(self) -> None:
        self.dispose_calls += 1


def _database_factory(engine: object) -> DatabaseFactory:
    resources = DatabaseResources(
        engine=cast(AsyncEngine, engine),
        session_factory=cast(
            async_sessionmaker[AsyncSession],
            Mock(),
        ),
    )
    return cast(DatabaseFactory, lambda _: resources)


def test_liveness_is_dependency_free(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "falcon-api"}


def test_api_v1_index_identifies_boundary(client: TestClient) -> None:
    response = client.get("/api/v1")

    assert response.status_code == 200
    assert response.json() == {"service": "falcon-api", "api_version": "v1"}


def test_liveness_does_not_accept_post(client: TestClient) -> None:
    assert client.post("/health/live").status_code == 405


def test_readiness_reports_ready_after_postgresql_probe(
    test_settings: Settings,
) -> None:
    engine = _ReadyEngine()

    with TestClient(
        create_app(
            test_settings,
            database_factory=_database_factory(engine),
        ),
    ) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "falcon-api"}
    assert engine.connect_calls == 1
    assert engine.connection.execute_calls == 1
    assert engine.dispose_calls == 1


def test_readiness_failure_is_safe_and_liveness_stays_independent(
    test_settings: Settings,
) -> None:
    engine = _UnavailableEngine()

    with TestClient(
        create_app(
            test_settings,
            database_factory=_database_factory(engine),
        ),
    ) as client:
        live_response = client.get("/health/live")
        assert engine.connect_calls == 0
        ready_response = client.get(
            "/health/ready",
            headers={"X-Request-ID": "database-unavailable-id"},
        )

    assert live_response.status_code == 200
    assert ready_response.status_code == 503
    assert ready_response.json()["error"] == {
        "code": "service_unavailable",
        "message": "The service is temporarily unavailable.",
        "request_id": "database-unavailable-id",
        "timestamp": ready_response.json()["error"]["timestamp"],
    }
    assert "TOP-SECRET" not in ready_response.text
    assert engine.connect_calls == 1
    assert engine.dispose_calls == 1
