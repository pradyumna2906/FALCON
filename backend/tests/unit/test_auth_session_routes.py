"""API contracts for refresh rotation, origin checks, and logout."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import session_lifecycle_service_from
from falcon_api.auth.session_lifecycle import (
    RefreshResult,
    SessionLifecycleService,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session


_NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)
_OLD_REFRESH_TOKEN = "O" * 43
_NEW_REFRESH_TOKEN = "N" * 43
_TRUSTED_ORIGIN = "https://app.falcon.test"
_UNTRUSTED_ORIGIN = "https://untrusted.example"
def _post_with_refresh_cookie(
    client: TestClient,
    path: str,
    *,
    origin: str,
):
    """Submit an authentication request with the refresh cookie."""
    client.cookies.set(
        "falcon_refresh_token",
        _OLD_REFRESH_TOKEN,
        path="/api/v1/auth",
    )

    try:
        return client.post(
            path,
            headers={"Origin": origin},
        )
    finally:
        client.cookies.clear()

@pytest.fixture
def session_dependencies(
    client: TestClient,
) -> tuple[Mock, AsyncMock]:
    """Override persistence and lifecycle services."""
    service = Mock(spec=SessionLifecycleService)
    service.refresh = AsyncMock()
    service.logout = AsyncMock()
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = (
        session_override
    )
    client.app.dependency_overrides[
        session_lifecycle_service_from
    ] = lambda: service

    try:
        yield service, session
    finally:
        client.app.dependency_overrides.clear()


def test_refresh_rotates_cookie_and_returns_access_token(
    client: TestClient,
    session_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = session_dependencies
    user_id = uuid4()
    session_id = uuid4()

    service.refresh.return_value = RefreshResult(
        user_id=user_id,
        session_id=session_id,
        access_token="new-access-token",
        access_token_expires_at=_NOW + timedelta(minutes=15),
        refresh_token=_NEW_REFRESH_TOKEN,
        refresh_token_expires_at=_NOW + timedelta(days=7),
    )

    response = _post_with_refresh_cookie(
        client,
        "/api/v1/auth/refresh",
        origin=_TRUSTED_ORIGIN,
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "new-access-token",
        "token_type": "bearer",
        "expires_at": "2026-08-19T14:15:00Z",
    }
    assert _OLD_REFRESH_TOKEN not in response.text
    assert _NEW_REFRESH_TOKEN not in response.text

    cookie = response.headers["set-cookie"]

    assert f"falcon_refresh_token={_NEW_REFRESH_TOKEN}" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Max-Age=604800" in cookie

    service.refresh.assert_awaited_once_with(
        session,
        token=_OLD_REFRESH_TOKEN,
    )


def test_refresh_without_cookie_uses_safe_failure(
    client: TestClient,
    session_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, _ = session_dependencies

    response = client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": _TRUSTED_ORIGIN},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == (
        "invalid_refresh_session"
    )
    service.refresh.assert_not_awaited()


@pytest.mark.parametrize("path", ["/refresh", "/logout"])
def test_cookie_mutation_rejects_untrusted_origin(
    client: TestClient,
    session_dependencies: tuple[Mock, AsyncMock],
    path: str,
) -> None:
    service, _ = session_dependencies

    response = _post_with_refresh_cookie(
        client,
        f"/api/v1/auth{path}",
        origin=_UNTRUSTED_ORIGIN,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    service.refresh.assert_not_awaited()
    service.logout.assert_not_awaited()


def test_refresh_propagates_safe_invalid_session_error(
    client: TestClient,
    session_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, _ = session_dependencies
    service.refresh.side_effect = ApplicationError(
        code="invalid_refresh_session",
        message="The refresh session is invalid or expired.",
        status_code=401,
    )

    response = _post_with_refresh_cookie(
        client,
        "/api/v1/auth/refresh",
    origin=_TRUSTED_ORIGIN,
)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == (
        "invalid_refresh_session"
    )
    assert _OLD_REFRESH_TOKEN not in response.text
    assert "set-cookie" not in response.headers


def test_logout_revokes_session_and_clears_cookie(
    client: TestClient,
    session_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = session_dependencies

    response = _post_with_refresh_cookie(
        client,
        "/api/v1/auth/logout",
        origin=_TRUSTED_ORIGIN,
    )

    assert response.status_code == 204
    assert response.content == b""
    service.logout.assert_awaited_once_with(
        session,
        token=_OLD_REFRESH_TOKEN,
    )

    cookie = response.headers["set-cookie"]

    assert "falcon_refresh_token=" in cookie
    assert "Max-Age=0" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie


def test_logout_without_cookie_remains_idempotent(
    client: TestClient,
    session_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = session_dependencies

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    service.logout.assert_awaited_once_with(
        session,
        token=None,
    )
    assert "Max-Age=0" in response.headers["set-cookie"]
