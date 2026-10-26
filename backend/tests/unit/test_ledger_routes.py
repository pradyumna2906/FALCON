"""API contracts for authenticated ledger setup operations."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.ledger import ledger_service_from
from falcon_api.auth.principal import AuthenticatedPrincipal, CurrentPrincipalService
from falcon_api.infrastructure.database import get_database_session
from falcon_api.ledger import LedgerService
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import AccountType, CategoryKind
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


_TOKEN = "signed-ledger-access-token"
_NOW = datetime(2026, 8, 20, 17, 0, tzinfo=UTC)


@pytest.fixture
def ledger_dependencies(
    client: TestClient,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AuthenticatedPrincipal]:
    """Override persistence, authentication, and ledger services."""
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="ledger-setup@example.com",
        display_name="Ledger Setup",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    ledger_service = AsyncMock(spec=LedgerService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: principal_service
    client.app.dependency_overrides[
        ledger_service_from
    ] = lambda: ledger_service

    try:
        yield ledger_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _account(user_id=None) -> Account:
    return Account(
        id=uuid4(),
        user_id=user_id or uuid4(),
        name="Primary Bank",
        account_type=AccountType.BANK,
        institution_name="State Bank",
        masked_reference="•••• 1234",
        currency="INR",
        opening_balance=Decimal("25000.0000"),
        opening_balance_date=date(2026, 8, 20),
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _category(*, user_id=None, is_system: bool = True) -> Category:
    return Category(
        id=uuid4(),
        user_id=None if is_system else user_id,
        name="Groceries",
        normalized_name="groceries",
        classification_code="groceries" if is_system else None,
        kind=CategoryKind.EXPENSE,
        parent_id=None,
        is_system=is_system,
        display_order=10,
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _payload() -> dict[str, object]:
    return {
        "name": "Primary Bank",
        "account_type": "bank",
        "institution_name": "State Bank",
        "masked_reference": "•••• 1234",
        "opening_balance": "25000.0000",
        "opening_balance_date": "2026-08-20",
    }


def test_create_account_uses_authenticated_owner_and_currency(
    client: TestClient,
    ledger_dependencies,
) -> None:
    service, principal_service, session, principal = ledger_dependencies
    account = _account(principal.user_id)
    service.create_account.return_value = account

    response = client.post(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_payload(),
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(account.id)
    assert response.json()["opening_balance"] == "25000.0000"
    assert "user_id" not in response.json()
    assert "archived_at" not in response.json()
    principal_service.authenticate.assert_awaited_once_with(
        session, token=_TOKEN
    )
    call = service.create_account.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["default_currency"] == "INR"
    assert call.kwargs["command"].currency is None


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": str(uuid4())},
        {"id": str(uuid4())},
        {"currency": "invalid"},
        {"opening_balance": "1.00001"},
    ],
)
def test_create_account_rejects_invalid_or_server_owned_values(
    client: TestClient,
    ledger_dependencies,
    extra: dict[str, object],
) -> None:
    service, _, _, _ = ledger_dependencies

    response = client.post(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json={**_payload(), **extra},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.create_account.assert_not_awaited()


def test_list_accounts_returns_only_public_items(
    client: TestClient,
    ledger_dependencies,
) -> None:
    service, _, session, principal = ledger_dependencies
    account = _account(principal.user_id)
    service.list_accounts.return_value = (account,)

    response = client.get(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Primary Bank"
    assert "user_id" not in response.json()["items"][0]
    service.list_accounts.assert_awaited_once_with(
        session, user_id=principal.user_id
    )


def test_list_categories_returns_system_and_private_public_items(
    client: TestClient,
    ledger_dependencies,
) -> None:
    service, _, session, principal = ledger_dependencies
    service.list_categories.return_value = (
        _category(),
        _category(user_id=principal.user_id, is_system=False),
    )

    response = client.get(
        "/api/v1/categories",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert "normalized_name" not in response.json()["items"][0]
    assert response.json()["items"][0]["classification_code"] == "groceries"
    assert "user_id" not in response.json()["items"][1]
    service.list_categories.assert_awaited_once_with(
        session, user_id=principal.user_id
    )


@pytest.mark.parametrize("path", ["/api/v1/accounts", "/api/v1/categories"])
def test_ledger_reads_require_authentication(
    client: TestClient,
    path: str,
) -> None:
    response = client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"


def test_openapi_documents_ledger_setup_contract(client: TestClient) -> None:
    document = client.get("/openapi.json").json()

    assert set(document["paths"]["/api/v1/accounts"]) >= {"get", "post"}
    assert set(document["paths"]["/api/v1/categories"]) >= {"get"}
    post = document["paths"]["/api/v1/accounts"]["post"]
    assert post["operationId"] == "create_account"
    assert post["security"] == [{"HTTPBearer": []}]
