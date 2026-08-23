"""API contract tests for authenticated transaction classification."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.classification import classification_service_from
from falcon_api.auth.principal import (
    AuthenticatedPrincipal,
    CurrentPrincipalService,
)
from falcon_api.classification.application import (
    TransactionClassificationService,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.schemas.classification import ClassificationResult
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


_TOKEN = "signed-classification-access-token"
_NOW = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)


@pytest.fixture
def classification_dependencies(
    client: TestClient,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AuthenticatedPrincipal]:
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="classification-user@example.com",
        display_name="Classification User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    classification_service = AsyncMock(spec=TransactionClassificationService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: principal_service
    client.app.dependency_overrides[
        classification_service_from
    ] = lambda: classification_service

    try:
        yield classification_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _result(transaction_id=None) -> ClassificationResult:
    return ClassificationResult(
        transaction_id=transaction_id or uuid4(),
        decision=ClassificationDecision.AUTOMATIC,
        source=ClassificationSource.RULE,
        category_code=ClassificationCategoryCode.FOOD_DINING,
        subcategory_code=ClassificationSubcategoryCode.FOOD_DELIVERY,
        confidence=Decimal("0.9900"),
        reason_codes=(ClassificationReasonCode.KNOWN_MERCHANT,),
        ruleset_version="2026.1",
    )


def test_single_route_uses_authenticated_owner_and_returns_safe_result(
    client: TestClient,
    classification_dependencies,
) -> None:
    service, principal_service, session, principal = classification_dependencies
    result = _result()
    service.classify_one.return_value = result

    response = client.post(
        f"/api/v1/transactions/{result.transaction_id}/classification",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "transaction_id": str(result.transaction_id),
        "decision": "automatic",
        "source": "rule",
        "category_code": "food_dining",
        "subcategory_code": "food_delivery",
        "confidence": "0.9900",
        "reason_codes": ["known_merchant"],
        "taxonomy_version": "2026.1",
        "ruleset_version": "2026.1",
        "model_version": None,
    }
    principal_service.authenticate.assert_awaited_once_with(
        session, token=_TOKEN
    )
    service.classify_one.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        transaction_id=result.transaction_id,
    )
    assert "user_id" not in response.json()
    assert "model_path" not in response.json()


def test_batch_route_preserves_only_server_results(
    client: TestClient,
    classification_dependencies,
) -> None:
    service, _, session, principal = classification_dependencies
    identifiers = (uuid4(), uuid4())
    results = tuple(_result(item) for item in identifiers)
    service.classify_batch.return_value = results

    response = client.post(
        "/api/v1/classifications/batch",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json={"transaction_ids": [str(item) for item in identifiers]},
    )

    assert response.status_code == 200
    assert [item["transaction_id"] for item in response.json()["items"]] == [
        str(item) for item in identifiers
    ]
    service.classify_batch.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        transaction_ids=identifiers,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"transaction_ids": []},
        {"transaction_ids": [str(uuid4())] * 2},
        {
            "transaction_ids": [str(uuid4())],
            "user_id": str(uuid4()),
        },
    ],
)
def test_batch_rejects_empty_duplicate_and_server_owned_fields(
    client: TestClient,
    classification_dependencies,
    payload: dict[str, object],
) -> None:
    service, _, _, _ = classification_dependencies

    response = client.post(
        "/api/v1/classifications/batch",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.classify_batch.assert_not_awaited()


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("transaction_not_found", 404),
        ("category_not_found", 404),
        ("classification_conflict", 409),
        ("invalid_classification_target", 422),
        ("classification_unavailable", 422),
    ],
)
def test_single_route_preserves_bounded_application_errors(
    client: TestClient,
    classification_dependencies,
    code: str,
    status_code: int,
) -> None:
    service, _, _, _ = classification_dependencies
    service.classify_one.side_effect = ApplicationError(
        code=code,
        message="A safe classification failure occurred.",
        status_code=status_code,
    )

    response = client.post(
        f"/api/v1/transactions/{uuid4()}/classification",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_classification_routes_require_authentication(
    client: TestClient,
    classification_dependencies,
) -> None:
    service, principal_service, session, _ = classification_dependencies
    principal_service.authenticate.side_effect = ApplicationError(
        code="invalid_access_token",
        message="The access token is invalid or expired.",
        status_code=401,
    )

    response = client.post(
        f"/api/v1/transactions/{uuid4()}/classification"
    )

    assert response.status_code == 401
    principal_service.authenticate.assert_awaited_once_with(session, token="")
    service.classify_one.assert_not_awaited()


def test_openapi_documents_single_and_batch_classification(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()

    assert "post" in document["paths"][
        "/api/v1/transactions/{transaction_id}/classification"
    ]
    assert "post" in document["paths"]["/api/v1/classifications/batch"]
    assert document["paths"]["/api/v1/classifications/batch"]["post"][
        "operationId"
    ] == "classify_transaction_batch"
