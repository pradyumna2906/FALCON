"""API contracts for password-reset request and confirmation."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import password_recovery_service_from
from falcon_api.auth.password_recovery import PasswordRecoveryService
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session


_RAW_TOKEN = "a" * 43
_NEW_PASSWORD = "New-Correct-Horse-Battery-Staple-2026!"
_TRUSTED_ORIGIN = "https://app.falcon.test"
_UNTRUSTED_ORIGIN = "https://untrusted.example"


@pytest.fixture
def password_recovery_dependencies(
    client: TestClient,
) -> tuple[Mock, AsyncMock]:
    """Override persistence and password-recovery dependencies."""
    service = Mock(spec=PasswordRecoveryService)
    service.request_password_reset = AsyncMock()
    service.confirm_password_reset = AsyncMock()
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = (
        session_override
    )
    client.app.dependency_overrides[
        password_recovery_service_from
    ] = lambda: service

    try:
        yield service, session
    finally:
        client.app.dependency_overrides.clear()


def test_password_reset_request_is_enumeration_resistant(
    client: TestClient,
    password_recovery_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = password_recovery_dependencies

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": " USER@EXAMPLE.COM "},
    )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    service.request_password_reset.assert_awaited_once_with(
        session,
        email="user@example.com",
    )


def test_password_reset_request_rejects_invalid_payload(
    client: TestClient,
    password_recovery_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, _ = password_recovery_dependencies

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 422
    service.request_password_reset.assert_not_awaited()


def test_password_reset_confirmation_changes_credential(
    client: TestClient,
    password_recovery_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, session = password_recovery_dependencies

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        headers={"Origin": _TRUSTED_ORIGIN},
        json={
            "token": _RAW_TOKEN,
            "new_password": _NEW_PASSWORD,
        },
    )

    assert response.status_code == 204
    assert response.content == b""
    service.confirm_password_reset.assert_awaited_once_with(
        session,
        token=_RAW_TOKEN,
        new_password=_NEW_PASSWORD,
    )


def test_password_reset_confirmation_rejects_untrusted_origin(
    client: TestClient,
    password_recovery_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, _ = password_recovery_dependencies

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        headers={"Origin": _UNTRUSTED_ORIGIN},
        json={
            "token": _RAW_TOKEN,
            "new_password": _NEW_PASSWORD,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    service.confirm_password_reset.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "token": "too-short",
            "new_password": _NEW_PASSWORD,
        },
        {
            "token": _RAW_TOKEN,
            "new_password": "too-short",
        },
        {
            "token": f"{_RAW_TOKEN}!",
            "new_password": _NEW_PASSWORD,
        },
    ],
)
def test_password_reset_confirmation_rejects_invalid_payload(
    client: TestClient,
    password_recovery_dependencies: tuple[Mock, AsyncMock],
    payload: dict[str, str],
) -> None:
    service, _ = password_recovery_dependencies

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        headers={"Origin": _TRUSTED_ORIGIN},
        json=payload,
    )

    assert response.status_code == 422
    service.confirm_password_reset.assert_not_awaited()


def test_password_reset_confirmation_propagates_safe_token_failure(
    client: TestClient,
    password_recovery_dependencies: tuple[Mock, AsyncMock],
) -> None:
    service, _ = password_recovery_dependencies
    service.confirm_password_reset.side_effect = ApplicationError(
        code="invalid_password_reset_token",
        message="The password-reset token is invalid or expired.",
        status_code=400,
    )

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        headers={"Origin": _TRUSTED_ORIGIN},
        json={
            "token": _RAW_TOKEN,
            "new_password": _NEW_PASSWORD,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == (
        "invalid_password_reset_token"
    )
    assert _RAW_TOKEN not in response.text
    assert _NEW_PASSWORD not in response.text
