"""Public forecasting API and schema contract checks."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.forecasting import forecasting_service_from
from falcon_api.auth.principal import AuthenticatedPrincipal, CurrentPrincipalService
from falcon_api.core.errors import ApplicationError
from falcon_api.forecasting import FinancialForecastService
from falcon_api.infrastructure.database import get_database_session
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


_NOW = datetime(2026, 9, 9, tzinfo=UTC)
_TOKEN = "signed-forecast-access-token"


@pytest.fixture
def forecasting_dependencies(
    client: TestClient,
) -> tuple[AsyncMock, AsyncMock, AuthenticatedPrincipal]:
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="forecast-user@example.com",
        display_name="Forecast User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    service = AsyncMock(spec=FinancialForecastService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[current_principal_service_from] = lambda: (
        principal_service
    )
    client.app.dependency_overrides[forecasting_service_from] = lambda: service
    try:
        yield service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _run(*, run_id=None, with_points: bool = True) -> dict[str, object]:
    return {
        "id": run_id or uuid4(),
        "created_at": _NOW,
        "target": "total_expense",
        "granularity": "month",
        "currency": "INR",
        "history_start": date(2026, 1, 1),
        "history_end": date(2026, 8, 31),
        "data_cutoff_at": _NOW,
        "source_last_updated_at": _NOW,
        "forecast_start": date(2026, 9, 1),
        "forecast_end": date(2026, 9, 1),
        "horizon": 1,
        "contract_version": "2026.1",
        "quality_policy_version": "2026.1",
        "evaluation_policy_version": "2026.1",
        "feature_policy_version": None,
        "selection_policy_version": "2026.1",
        "uncertainty_policy_version": "2026.1",
        "model_code": "last_value",
        "model_version": "adapter-2026.1",
        "model_parameters": {},
        "candidate_evidence": {"quality_eligibility": "normal"},
        "selection_metric": "wape",
        "validation_mae": Decimal("1"),
        "validation_rmse": Decimal("1"),
        "validation_wape": Decimal("0.01"),
        "validation_bias": Decimal("0"),
        "test_mae": Decimal("2"),
        "test_rmse": Decimal("2"),
        "test_wape": Decimal("0.02"),
        "test_bias": Decimal("0"),
        "uncertainty_method": "absolute_residual_conformal",
        "uncertainty_reliability": "normal",
        "points": (
            {
                "step": 1,
                "period_start": date(2026, 9, 1),
                "expected_value": Decimal("100"),
                "lower_80": Decimal("90"),
                "upper_80": Decimal("110"),
                "lower_95": Decimal("80"),
                "upper_95": Decimal("120"),
            },
        )
        if with_points
        else (),
    }


def _summary(run_id) -> dict[str, object]:
    run = _run(run_id=run_id, with_points=False)
    fields = {
        "id",
        "created_at",
        "target",
        "granularity",
        "currency",
        "forecast_start",
        "forecast_end",
        "horizon",
        "model_code",
        "uncertainty_reliability",
    }
    return {field: run[field] for field in fields}


def test_generate_uses_authenticated_owner_timezone_and_default_currency(
    client: TestClient,
    forecasting_dependencies: tuple[AsyncMock, AsyncMock, AuthenticatedPrincipal],
) -> None:
    service, session, principal = forecasting_dependencies
    service.generate.return_value = _run()
    response = client.post(
        "/api/v1/forecasts",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json={
            "target": "total_expense",
            "granularity": "month",
            "history_start": "2026-01-01",
            "history_end": "2026-08-31",
            "horizon": 1,
        },
    )
    assert response.status_code == 201
    assert response.json()["currency"] == "INR"
    assert service.generate.await_args.args == (session,)
    assert service.generate.await_args.kwargs["user_id"] == principal.user_id
    command = service.generate.await_args.kwargs["command"]
    assert command.trusted_timezone == principal.timezone
    assert command.currency == principal.default_currency


def test_generate_normalizes_currency_and_rejects_invalid_request_bounds(
    client: TestClient,
    forecasting_dependencies: tuple[AsyncMock, AsyncMock, AuthenticatedPrincipal],
) -> None:
    service, _, _ = forecasting_dependencies
    service.generate.return_value = _run()
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    payload = {
        "target": "total_expense",
        "granularity": "month",
        "currency": "usd",
        "history_start": "2026-01-01",
        "history_end": "2026-08-31",
        "horizon": 1,
    }
    response = client.post("/api/v1/forecasts", headers=headers, json=payload)
    assert response.status_code == 201
    assert service.generate.await_args.kwargs["command"].currency == "USD"

    reversed_range = client.post(
        "/api/v1/forecasts",
        headers=headers,
        json={**payload, "history_start": "2026-09-01"},
    )
    oversized_monthly = client.post(
        "/api/v1/forecasts",
        headers=headers,
        json={**payload, "horizon": 25},
    )
    assert reversed_range.status_code == 422
    assert oversized_monthly.status_code == 422


def test_get_and_list_are_owner_scoped_and_not_found_is_normalized(
    client: TestClient,
    forecasting_dependencies: tuple[AsyncMock, AsyncMock, AuthenticatedPrincipal],
) -> None:
    service, _, principal = forecasting_dependencies
    run_id = uuid4()
    service.get.return_value = _run(run_id=run_id)
    service.list_recent.return_value = (_summary(run_id),)
    headers = {"Authorization": f"Bearer {_TOKEN}"}

    get_response = client.get(f"/api/v1/forecasts/{run_id}", headers=headers)
    list_response = client.get("/api/v1/forecasts?limit=5", headers=headers)
    assert get_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == str(run_id)
    assert service.get.await_args.kwargs["user_id"] == principal.user_id
    assert service.list_recent.await_args.kwargs == {
        "user_id": principal.user_id,
        "limit": 5,
    }

    service.get.side_effect = ApplicationError(
        code="forecast_not_found",
        message="The requested forecast was not found.",
        status_code=404,
    )
    missing = client.get(f"/api/v1/forecasts/{uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "forecast_not_found"


def test_openapi_documents_authenticated_forecast_generation_and_history(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    assert set(paths["/api/v1/forecasts"]) == {"get", "post"}
    assert set(paths["/api/v1/forecasts/{run_id}"]) == {"get"}
    for operation in (
        paths["/api/v1/forecasts"]["get"],
        paths["/api/v1/forecasts"]["post"],
        paths["/api/v1/forecasts/{run_id}"]["get"],
    ):
        assert operation["security"] == [{"HTTPBearer": []}]


def test_forecast_request_excludes_owner_cutoff_and_model_controls(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    properties = schemas["ForecastGenerationRequest"]["properties"]
    assert set(properties) == {
        "target",
        "granularity",
        "currency",
        "history_start",
        "history_end",
        "horizon",
    }
    assert not {"user_id", "data_cutoff_at", "model_code", "parameters"} & properties.keys()
