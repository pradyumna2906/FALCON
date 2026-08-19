"""API contracts for bearer authentication and the current user."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.auth.principal import (
    AuthenticatedPrincipal,
    CurrentPrincipalService,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session


_TOKEN = "signed-access-token"


@pytest.fixture
def principal_dependencies(
    client: TestClient,
) -> tuple[Mock, AsyncMock]:
    """Override persistence and principal resolution."""
    service = Mock(spec=CurrentPrincipalService)
    service.authenticate = AsyncMock()
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = (
        session_override
    )
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: service

    try:
        yield service, session
    finally:
        client.app.dependency_overrides.clear()


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="user@example.com",
        display_name="Current User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def test_current_user_returns_non_sensitive_identity(
    client: TestClient,
    principal_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = principal_dependencies
    principal = _principal()
    service.authenticate.return_value = principal

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(principal.user_id),
        "email": "user@example.com",
        "display_name": "Current User",
        "timezone": "Asia/Kolkata",
        "default_currency": "INR",
        "email_verified": True,
    }
    assert "password" not in response.text
    assert "token" not in response.text
    assert "session_id" not in response.text
    service.authenticate.assert_awaited_once_with(
        session,
        token=_TOKEN,
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic credentials"},
    ],
)
def test_current_user_uses_uniform_missing_credential_failure(
    client: TestClient,
    principal_dependencies: tuple[Mock, AsyncMock],
    headers: dict[str, str],
) -> None:
    service, session = principal_dependencies
    service.authenticate.side_effect = ApplicationError(
        code="invalid_access_token",
        message="The access token is invalid or expired.",
        status_code=401,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"
    service.authenticate.assert_awaited_once_with(
        session,
        token="",
    )


def test_current_user_propagates_invalid_bearer_failure(
    client: TestClient,
    principal_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = principal_dependencies
    service.authenticate.side_effect = ApplicationError(
        code="invalid_access_token",
        message="The access token is invalid or expired.",
        status_code=401,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"
    assert _TOKEN not in response.text
    service.authenticate.assert_awaited_once_with(
        session,
        token=_TOKEN,
    )


def test_current_user_openapi_requires_bearer_authentication(
    client: TestClient,
) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/auth/me"
    ]["get"]

    assert operation["operationId"] == "get_current_user"
    assert operation["security"] == [{"HTTPBearer": []}]
