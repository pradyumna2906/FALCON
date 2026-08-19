"""API-contract tests for registration and email verification."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import registration_service_from
from falcon_api.auth.registration import (
    RegistrationResult,
    RegistrationService,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session


def _service() -> Mock:
    service = Mock(spec=RegistrationService)
    service.register = AsyncMock()
    service.request_email_verification = AsyncMock()
    service.confirm_email_verification = AsyncMock()
    return service


@pytest.fixture
def auth_dependencies(
    client: TestClient,
) -> tuple[Mock, AsyncMock]:
    service = _service()
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = (
        session_override
    )
    client.app.dependency_overrides[registration_service_from] = (
        lambda: service
    )

    try:
        yield service, session
    finally:
        client.app.dependency_overrides.clear()


def test_registration_returns_minimal_unverified_identity(
    client: TestClient,
    auth_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = auth_dependencies
    user_id = uuid4()
    service.register.return_value = RegistrationResult(
        user_id=user_id,
        email="user@example.com",
    )

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": " User@Example.COM ",
            "password": "correct horse battery staple",
            "display_name": "  Pradyumna  ",
            "timezone": "Asia/Kolkata",
            "default_currency": "INR",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": str(user_id),
        "email": "user@example.com",
        "email_verified": False,
    }

    command = service.register.await_args.args[1]
    assert service.register.await_args.args[0] is session
    assert command.email == "user@example.com"
    assert command.password == "correct horse battery staple"
    assert command.display_name == "Pradyumna"


def test_registration_conflict_uses_safe_error_contract(
    client: TestClient,
    auth_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, _ = auth_dependencies
    service.register.side_effect = ApplicationError(
        code="email_already_registered",
        message="An account with this email address already exists.",
        status_code=409,
    )

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "correct horse battery staple",
        },
        headers={"X-Request-ID": "registration-conflict-id"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "email_already_registered"
    )
    assert response.json()["error"]["request_id"] == (
        "registration-conflict-id"
    )
    assert "password" not in response.text


def test_registration_validation_does_not_reflect_password(
    client: TestClient,
    auth_dependencies: tuple[Mock, AsyncMock],
) -> None:
    password = "secret"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": password,
        },
    )

    assert response.status_code == 422
    assert password not in response.text


@pytest.mark.parametrize(
    "email",
    [
        "user@example.com",
        "unknown@example.com",
    ],
)
def test_verification_request_has_generic_response(
    client: TestClient,
    auth_dependencies: tuple[Mock, AsyncMock],
    email: str,
) -> None:
    service, session = auth_dependencies

    response = client.post(
        "/api/v1/auth/email-verification/request",
        json={"email": email},
    )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    service.request_email_verification.assert_awaited_once_with(
        session,
        email=email,
    )


def test_verification_confirmation_returns_no_content(
    client: TestClient,
    auth_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = auth_dependencies
    token = "A" * 43

    response = client.post(
        "/api/v1/auth/email-verification/confirm",
        json={"token": token},
    )

    assert response.status_code == 204
    assert response.content == b""
    service.confirm_email_verification.assert_awaited_once_with(
        session,
        token=token,
    )


def test_invalid_verification_token_uses_safe_error_contract(
    client: TestClient,
    auth_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, _ = auth_dependencies
    service.confirm_email_verification.side_effect = ApplicationError(
        code="invalid_verification_token",
        message="The email-verification token is invalid or expired.",
        status_code=400,
    )

    response = client.post(
        "/api/v1/auth/email-verification/confirm",
        json={"token": "A" * 43},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == (
        "invalid_verification_token"
    )
    assert "A" * 43 not in response.text


def test_authentication_routes_reject_unknown_fields(
    client: TestClient,
    auth_dependencies: tuple[Mock, AsyncMock],
) -> None:
    response = client.post(
        "/api/v1/auth/email-verification/request",
        json={
            "email": "user@example.com",
            "unknown": "value",
        },
    )

    assert response.status_code == 422


def test_openapi_exposes_only_approved_phase_3_4_routes(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/email-verification/request" in paths
    assert "/api/v1/auth/email-verification/confirm" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" not in paths
