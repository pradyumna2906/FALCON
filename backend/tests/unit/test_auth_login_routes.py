"""API-contract tests for secure login and refresh-cookie issuance."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import login_service_from
from falcon_api.auth.login import LoginResult, LoginService
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session


_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
_REFRESH_TOKEN = "R" * 43
_ACCESS_TOKEN = "encoded-access-token"


@pytest.fixture
def login_dependencies(
    client: TestClient,
) -> tuple[Mock, AsyncMock]:
    """Replace database and login dependencies with isolated mocks."""
    service = Mock(spec=LoginService)
    service.login = AsyncMock()
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = (
        session_override
    )
    client.app.dependency_overrides[login_service_from] = (
        lambda: service
    )

    try:
        yield service, session
    finally:
        client.app.dependency_overrides.clear()


def test_login_returns_access_token_and_protected_refresh_cookie(
    client: TestClient,
    login_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = login_dependencies
    user_id = uuid4()
    session_id = uuid4()

    service.login.return_value = LoginResult(
        user_id=user_id,
        session_id=session_id,
        access_token=_ACCESS_TOKEN,
        access_token_expires_at=_NOW + timedelta(minutes=15),
        refresh_token=_REFRESH_TOKEN,
        refresh_token_expires_at=_NOW + timedelta(days=7),
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": " User@Example.COM ",
            "password": "correct horse battery staple",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": _ACCESS_TOKEN,
        "token_type": "bearer",
        "expires_at": "2026-08-19T12:15:00Z",
    }
    assert _REFRESH_TOKEN not in response.text

    cookie = response.headers["set-cookie"]

    assert "falcon_refresh_token=" in cookie
    assert _REFRESH_TOKEN in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=604800" in cookie

    if client.app.state.settings.env.value == "development":
        assert "Secure" not in cookie
    else:
        assert "Secure" in cookie

    command = service.login.await_args.args[1]

    assert service.login.await_args.args[0] is session
    assert command.email == "user@example.com"
    assert command.password == "correct horse battery staple"


@pytest.mark.parametrize(
    "failure_reason",
    [
        "unknown_email",
        "wrong_password",
        "disabled_user",
    ],
)
def test_login_failure_uses_one_safe_public_contract(
    client: TestClient,
    login_dependencies: tuple[Mock, AsyncMock],
    failure_reason: str,
) -> None:
    service, _ = login_dependencies
    service.login.side_effect = ApplicationError(
        code="invalid_credentials",
        message="The email address or password is incorrect.",
        status_code=401,
    )
    password = f"private-{failure_reason}-password"

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": password,
        },
        headers={"X-Request-ID": "login-failure-id"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.json()["error"]["request_id"] == "login-failure-id"
    assert password not in response.text
    assert "set-cookie" not in response.headers


def test_login_validation_does_not_reflect_password(
    client: TestClient,
    login_dependencies: tuple[Mock, AsyncMock],
) -> None:
    password = "x" * 129

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": password,
        },
    )

    assert response.status_code == 422
    assert password not in response.text


def test_login_rejects_unknown_request_fields(
    client: TestClient,
    login_dependencies: tuple[Mock, AsyncMock],
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "correct horse battery staple",
            "remember_me": True,
        },
    )

    assert response.status_code == 422


def test_openapi_exposes_session_lifecycle_routes(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/auth/me" in paths
