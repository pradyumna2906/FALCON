"""API contracts for authenticated transaction operations."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.transactions import transaction_service_from
from falcon_api.auth.principal import (
    AuthenticatedPrincipal,
    CurrentPrincipalService,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.models.enums import (
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.transactions import (
    TransactionPage,
    TransactionService,
    TransactionView,
    TransferResult,
)
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


_TOKEN = "signed-transaction-access-token"
_NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


@pytest.fixture
def transaction_dependencies(
    client: TestClient,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AuthenticatedPrincipal]:
    """Override persistence, authentication, and transaction services."""
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="ledger-user@example.com",
        display_name="Ledger User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    transaction_service = AsyncMock(spec=TransactionService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: principal_service
    client.app.dependency_overrides[
        transaction_service_from
    ] = lambda: transaction_service

    try:
        yield transaction_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _view(
    *,
    transaction_type: TransactionType = TransactionType.EXPENSE,
    amount: Decimal = Decimal("1250.5000"),
) -> TransactionView:
    return TransactionView(
        id=uuid4(),
        account_id=uuid4(),
        category_id=uuid4(),
        transaction_type=transaction_type,
        amount=amount,
        transaction_date=date(2026, 8, 20),
        description="Monthly groceries",
        merchant_name="Local Market",
        source_type=TransactionSourceType.MANUAL,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _payload() -> dict[str, object]:
    return {
        "account_id": str(uuid4()),
        "category_id": str(uuid4()),
        "transaction_type": "expense",
        "amount": "1250.5000",
        "transaction_date": "2026-08-20",
        "description": "Monthly groceries",
        "merchant_name": "Local Market",
    }


def _assert_transaction_response(response, view: TransactionView) -> None:
    assert response.json() == {
        "id": str(view.id),
        "account_id": str(view.account_id),
        "category_id": str(view.category_id),
        "transaction_type": view.transaction_type.value,
        "amount": str(view.amount),
        "transaction_date": "2026-08-20",
        "description": "Monthly groceries",
        "merchant_name": "Local Market",
        "source_type": view.source_type.value,
        "status": "posted",
        "is_user_modified": False,
        "created_at": "2026-08-20T15:00:00Z",
        "updated_at": "2026-08-20T15:00:00Z",
    }
    assert "user_id" not in response.json()
    assert "external_source_hash" not in response.json()


def test_create_manual_uses_authenticated_identity_and_timezone(
    client: TestClient,
    transaction_dependencies,
) -> None:
    service, principal_service, session, principal = transaction_dependencies
    view = _view()
    service.create_manual.return_value = view

    response = client.post(
        "/api/v1/transactions",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_payload(),
    )

    assert response.status_code == 201
    _assert_transaction_response(response, view)
    principal_service.authenticate.assert_awaited_once_with(
        session, token=_TOKEN
    )
    call = service.create_manual.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["timezone"] == principal.timezone
    assert call.kwargs["command"].amount == Decimal("1250.5000")
    assert call.kwargs["command"].transaction_type is TransactionType.EXPENSE


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": str(uuid4())},
        {"status": "posted"},
        {"source_type": "manual"},
        {"amount": "-1"},
        {"transaction_type": "transfer"},
    ],
)
def test_create_rejects_invalid_or_server_owned_values(
    client: TestClient,
    transaction_dependencies,
    extra: dict[str, object],
) -> None:
    service, _, _, _ = transaction_dependencies
    payload = {**_payload(), **extra}

    response = client.post(
        "/api/v1/transactions",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.create_manual.assert_not_awaited()


def test_list_maps_filters_and_returns_public_page(
    client: TestClient,
    transaction_dependencies,
) -> None:
    service, _, session, principal = transaction_dependencies
    view = _view()
    account_id = uuid4()
    category_id = uuid4()
    service.list.return_value = TransactionPage((view,), "next.cursor")

    response = client.get(
        "/api/v1/transactions",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={
            "account_id": str(account_id),
            "category_id": str(category_id),
            "transaction_type": "expense",
            "status": "posted",
            "date_from": "2026-08-01",
            "date_to": "2026-08-20",
            "cursor": "current.cursor",
            "limit": "25",
        },
    )

    assert response.status_code == 200
    assert response.json()["next_cursor"] == "next.cursor"
    assert len(response.json()["items"]) == 1
    call = service.list.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["cursor_token"] == "current.cursor"
    assert call.kwargs["limit"] == 25
    filters = call.kwargs["filters"]
    assert filters.account_id == account_id
    assert filters.category_id == category_id
    assert filters.transaction_type is TransactionType.EXPENSE
    assert filters.status is TransactionStatus.POSTED


def test_list_rejects_unknown_query_and_inverted_dates(
    client: TestClient,
    transaction_dependencies,
) -> None:
    service, _, _, _ = transaction_dependencies

    for params in (
        {"user_id": str(uuid4())},
        {"date_from": "2026-08-21", "date_to": "2026-08-20"},
        {"limit": "101"},
    ):
        response = client.get(
            "/api/v1/transactions",
            headers={"Authorization": f"Bearer {_TOKEN}"},
            params=params,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    service.list.assert_not_awaited()


def test_get_replace_and_delete_use_owned_identifier(
    client: TestClient,
    transaction_dependencies,
) -> None:
    service, _, session, principal = transaction_dependencies
    view = _view()
    transaction_id = view.id
    service.get.return_value = view
    service.replace_manual.return_value = view

    get_response = client.get(
        f"/api/v1/transactions/{transaction_id}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    put_response = client.put(
        f"/api/v1/transactions/{transaction_id}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_payload(),
    )
    delete_response = client.delete(
        f"/api/v1/transactions/{transaction_id}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert get_response.status_code == 200
    assert put_response.status_code == 200
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    service.get.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        transaction_id=transaction_id,
    )
    replace = service.replace_manual.await_args.kwargs
    assert replace["user_id"] == principal.user_id
    assert replace["timezone"] == principal.timezone
    assert replace["transaction_id"] == transaction_id
    service.delete_manual.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        transaction_id=transaction_id,
    )


def test_create_transfer_uses_trusted_principal_context(
    client: TestClient,
    transaction_dependencies,
) -> None:
    service, _, session, principal = transaction_dependencies
    debit = _view(
        transaction_type=TransactionType.TRANSFER,
        amount=Decimal("500.0000"),
    )
    credit = _view(
        transaction_type=TransactionType.TRANSFER,
        amount=Decimal("500.0000"),
    )
    transfer_id = uuid4()
    service.create_transfer.return_value = TransferResult(
        transfer_id, debit, credit
    )
    source_id = uuid4()
    destination_id = uuid4()

    response = client.post(
        "/api/v1/transfers",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json={
            "source_account_id": str(source_id),
            "destination_account_id": str(destination_id),
            "amount": "500.0000",
            "transaction_date": "2026-08-20",
            "description": "Move to savings",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(transfer_id)
    assert response.json()["debit"]["amount"] == "500.0000"
    call = service.create_transfer.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["timezone"] == principal.timezone
    assert call.kwargs["command"].source_account_id == source_id
    assert call.kwargs["command"].destination_account_id == destination_id


def test_routes_preserve_safe_service_errors(
    client: TestClient,
    transaction_dependencies,
) -> None:
    service, _, _, _ = transaction_dependencies
    service.get.side_effect = ApplicationError(
        code="transaction_not_found",
        message="The transaction was not found.",
        status_code=404,
    )

    response = client.get(
        f"/api/v1/transactions/{uuid4()}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"


def test_routes_require_uniform_bearer_authentication(
    client: TestClient,
    transaction_dependencies,
) -> None:
    service, principal_service, session, _ = transaction_dependencies
    principal_service.authenticate.side_effect = ApplicationError(
        code="invalid_access_token",
        message="The access token is invalid or expired.",
        status_code=401,
    )

    response = client.get("/api/v1/transactions")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"
    principal_service.authenticate.assert_awaited_once_with(session, token="")
    service.list.assert_not_awaited()


def test_transaction_openapi_documents_operations_and_security(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    collection = paths["/api/v1/transactions"]
    item = paths["/api/v1/transactions/{transaction_id}"]
    transfer = paths["/api/v1/transfers"]

    assert set(collection) == {"get", "post"}
    assert set(item) == {"get", "put", "delete"}
    assert set(transfer) == {"post"}
    for operation in (*collection.values(), *item.values(), *transfer.values()):
        assert operation["security"] == [{"HTTPBearer": []}]
    assert item["delete"]["responses"]["204"]["description"]
    assert "409" in item["put"]["responses"]
    assert "422" in collection["get"]["responses"]


def test_transaction_openapi_excludes_private_fields(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    request = set(schemas["ManualTransactionCreateRequest"]["properties"])
    response = set(schemas["TransactionResponse"]["properties"])

    for private in {
        "user_id",
        "source_type",
        "status",
        "external_source_hash",
        "import_job_id",
    }:
        assert private not in request
    assert "user_id" not in response
    assert "external_source_hash" not in response
