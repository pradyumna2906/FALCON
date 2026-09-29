"""API contracts for authenticated financial-profile operations."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.profile import financial_profile_service_from
from falcon_api.auth.principal import (
    AuthenticatedPrincipal,
    CurrentPrincipalService,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
)
from falcon_api.models.user import FinancialProfile
from falcon_api.profile import (
    FinancialProfileMutationResult,
    FinancialProfileService,
)


_TOKEN = "signed-profile-access-token"
_NOW = datetime(2026, 8, 19, 22, 0, tzinfo=UTC)


@pytest.fixture
def profile_dependencies(
    client: TestClient,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AuthenticatedPrincipal]:
    """Override persistence, authentication, and profile services."""
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="user@example.com",
        display_name="Profile User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    profile_service = AsyncMock(spec=FinancialProfileService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = (
        session_override
    )
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: principal_service
    client.app.dependency_overrides[
        financial_profile_service_from
    ] = lambda: profile_service

    try:
        yield profile_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _profile(user_id) -> FinancialProfile:
    return FinancialProfile(
        id=uuid4(),
        user_id=user_id,
        income_pattern=IncomePattern.SALARIED,
        income_stability=IncomeStability.STABLE,
        has_household_responsibilities=True,
        dependant_count=2,
        emergency_fund_target_months=Decimal("6.00"),
        completion_status=ProfileCompletionStatus.COMPLETE,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _payload() -> dict[str, object]:
    return {
        "income_pattern": "salaried",
        "income_stability": "stable",
        "has_household_responsibilities": True,
        "dependant_count": 2,
        "emergency_fund_target_months": "6.00",
    }


def _assert_profile_response(response, profile: FinancialProfile) -> None:
    assert response.json() == {
        "id": str(profile.id),
        "income_pattern": "salaried",
        "income_stability": "stable",
        "has_household_responsibilities": True,
        "dependant_count": 2,
        "emergency_fund_target_months": "6.00",
        "completion_status": "complete",
        "created_at": "2026-08-19T22:00:00Z",
        "updated_at": "2026-08-19T22:00:00Z",
    }
    assert "user_id" not in response.json()


def test_get_profile_returns_only_authenticated_users_profile(
    client: TestClient,
    profile_dependencies,
) -> None:
    service, principal_service, session, principal = profile_dependencies
    profile = _profile(principal.user_id)
    service.get.return_value = profile

    response = client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    _assert_profile_response(response, profile)
    principal_service.authenticate.assert_awaited_once_with(
        session,
        token=_TOKEN,
    )
    service.get.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
    )


def test_get_profile_returns_safe_not_found_error(
    client: TestClient,
    profile_dependencies,
) -> None:
    service, _, _, _ = profile_dependencies
    service.get.side_effect = ApplicationError(
        code="profile_not_found",
        message="A financial profile has not been created.",
        status_code=404,
    )

    response = client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


@pytest.mark.parametrize(
    ("created", "expected_status"),
    [(True, 201), (False, 200)],
)
def test_put_profile_distinguishes_creation_and_replacement(
    client: TestClient,
    profile_dependencies,
    created: bool,
    expected_status: int,
) -> None:
    service, _, session, principal = profile_dependencies
    profile = _profile(principal.user_id)
    service.put.return_value = FinancialProfileMutationResult(
        profile=profile,
        created=created,
    )

    response = client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_payload(),
    )

    assert response.status_code == expected_status
    _assert_profile_response(response, profile)
    assert service.put.await_args.args == (session,)
    command = service.put.await_args.kwargs["command"]
    assert service.put.await_args.kwargs["user_id"] == principal.user_id
    assert command.income_pattern is IncomePattern.SALARIED
    assert command.income_stability is IncomeStability.STABLE
    assert command.has_household_responsibilities is True
    assert command.dependant_count == 2
    assert command.emergency_fund_target_months == Decimal("6.00")


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            **_payload(),
            "dependant_count": -1,
        },
        {
            **_payload(),
            "income_pattern": "unsupported",
        },
        {
            **_payload(),
            "user_id": str(uuid4()),
        },
        {
            **_payload(),
            "has_household_responsibilities": False,
        },
    ],
)
def test_put_profile_rejects_invalid_or_owner_controlled_values(
    client: TestClient,
    profile_dependencies,
    invalid_payload: dict[str, object],
) -> None:
    service, _, _, _ = profile_dependencies

    response = client.put(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=invalid_payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.put.assert_not_awaited()


def test_profile_route_uses_uniform_missing_credential_failure(
    client: TestClient,
    profile_dependencies,
) -> None:
    service, principal_service, session, _ = profile_dependencies
    principal_service.authenticate.side_effect = ApplicationError(
        code="invalid_access_token",
        message="The access token is invalid or expired.",
        status_code=401,
    )

    response = client.get("/api/v1/profile")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"
    principal_service.authenticate.assert_awaited_once_with(
        session,
        token="",
    )
    service.get.assert_not_awaited()


def test_profile_openapi_exposes_only_get_and_put_with_bearer_security(
    client: TestClient,
) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/profile"
    ]

    assert set(operation) == {"get", "put"}
    assert operation["get"]["operationId"] == "get_financial_profile"
    assert operation["put"]["operationId"] == "put_financial_profile"
    assert operation["get"]["security"] == [{"HTTPBearer": []}]
    assert operation["put"]["security"] == [{"HTTPBearer": []}]
    assert set(operation["get"]["responses"]) >= {"200", "401", "404"}
    assert set(operation["put"]["responses"]) >= {
        "200",
        "201",
        "401",
        "422",
    }


def test_profile_openapi_uses_strict_request_and_public_response(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    request_properties = set(
        schemas["FinancialProfilePutRequest"]["properties"]
    )
    response_properties = set(
        schemas["FinancialProfileResponse"]["properties"]
    )

    assert "user_id" not in request_properties
    assert "completion_status" not in request_properties
    assert "user_id" not in response_properties
    assert "completion_status" in response_properties
