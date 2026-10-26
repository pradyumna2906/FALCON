"""Checkpoint 11.13 authenticated scenario API and OpenAPI tests."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.scenarios import scenario_simulation_service_from
from falcon_api.auth.principal import AuthenticatedPrincipal, CurrentPrincipalService
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.scenario_simulation import ScenarioSimulationService
from goal_plan_test_data import OWNER_ID
from scenario_test_data import SNAPSHOT_NOW, transient_scenario_run


TOKEN = "signed-scenario-access-token"
RUN = transient_scenario_run()


@pytest.fixture
def scenario_dependencies(client: TestClient):
    principal = AuthenticatedPrincipal(
        user_id=OWNER_ID,
        session_id=uuid4(),
        email="scenario-owner@example.com",
        display_name="Scenario Owner",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=SNAPSHOT_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    service = AsyncMock(spec=ScenarioSimulationService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[current_principal_service_from] = (
        lambda: principal_service
    )
    client.app.dependency_overrides[scenario_simulation_service_from] = (
        lambda: service
    )
    try:
        yield service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _payload() -> dict[str, object]:
    return {
        "source_plan_id": str(RUN.source_plan_id),
        "scenarios": [
            {
                "name": "Income pressure",
                "income_change_percent": "-10",
            }
        ],
    }


def test_simulate_derives_owner_and_returns_complete_public_evidence(
    client: TestClient,
    scenario_dependencies,
) -> None:
    service, principal_service, session, principal = scenario_dependencies
    service.simulate.return_value = RUN

    response = client.post(
        "/api/v1/scenario-simulations",
        headers=_headers(),
        json=_payload(),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] == str(RUN.id)
    assert payload["root_seed"] == 23
    assert payload["trial_count"] == 64
    assert len(payload["definitions"]) == 4
    assert len(payload["comparisons"]) == 4
    assert payload["definitions"][-1]["assumptions"]["name"] == (
        "Unexpected expense"
    )
    assert "user_id" not in repr(payload)
    call = service.simulate.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["command"].source_plan_id == RUN.source_plan_id
    assert call.kwargs["command"].scenarios[0].name == "Income pressure"
    principal_service.authenticate.assert_awaited_once_with(session, token=TOKEN)


@pytest.mark.parametrize(
    "server_field",
    [
        "user_id",
        "cutoff_at",
        "trial_count",
        "seed",
        "probability_method",
        "policy_versions",
        "raw_transactions",
    ],
)
def test_simulate_rejects_server_owned_inputs(
    client: TestClient,
    scenario_dependencies,
    server_field: str,
) -> None:
    service, _, _, _ = scenario_dependencies
    payload = _payload()
    payload[server_field] = "untrusted"

    response = client.post(
        "/api/v1/scenario-simulations",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 422
    service.simulate.assert_not_awaited()


def test_list_is_bounded_owner_scoped_and_compact(
    client: TestClient,
    scenario_dependencies,
) -> None:
    service, _, session, principal = scenario_dependencies
    service.list_recent.return_value = (RUN,)

    response = client.get(
        "/api/v1/scenario-simulations?limit=25",
        headers=_headers(),
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == str(RUN.id)
    assert "definitions" not in item
    assert "comparisons" not in item
    assert "root_seed" not in item
    service.list_recent.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        limit=25,
    )


@pytest.mark.parametrize("limit", [0, 101])
def test_list_rejects_out_of_bounds_limits(
    client: TestClient,
    scenario_dependencies,
    limit: int,
) -> None:
    service, _, _, _ = scenario_dependencies
    response = client.get(
        f"/api/v1/scenario-simulations?limit={limit}",
        headers=_headers(),
    )
    assert response.status_code == 422
    service.list_recent.assert_not_awaited()


def test_get_and_compare_use_only_authenticated_owner(
    client: TestClient,
    scenario_dependencies,
) -> None:
    service, _, session, principal = scenario_dependencies
    service.get.return_value = RUN
    service.compare.return_value = RUN

    detail = client.get(
        f"/api/v1/scenario-simulations/{RUN.id}",
        headers=_headers(),
    )
    comparison = client.get(
        f"/api/v1/scenario-simulations/{RUN.id}/compare",
        headers=_headers(),
    )

    assert detail.status_code == 200
    assert detail.json()["snapshot_id"] == RUN.snapshot_id
    assert comparison.status_code == 200
    body = comparison.json()
    assert body["simulation_run_id"] == str(RUN.id)
    assert len(body["definitions"]) == 4
    assert body["definitions"][-1]["name"] == "Unexpected expense"
    assert len(body["items"]) == 4
    assert sum(item["recommended"] for item in body["items"]) == 1
    service.get.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        run_id=RUN.id,
    )
    service.compare.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        run_id=RUN.id,
    )


@pytest.mark.parametrize("target", ["definition", None])
def test_select_and_clear_forward_compare_and_set_state(
    client: TestClient,
    scenario_dependencies,
    target,
) -> None:
    service, _, session, principal = scenario_dependencies
    service.select.return_value = RUN
    definition_id = RUN.definitions[0].id if target == "definition" else None

    response = client.post(
        f"/api/v1/scenario-simulations/{RUN.id}/select",
        headers=_headers(),
        json={
            "scenario_definition_id": (
                str(definition_id) if definition_id is not None else None
            ),
            "expected_selected_scenario_id": None,
        },
    )

    assert response.status_code == 200
    command = service.select.await_args.kwargs["command"]
    assert command.scenario_definition_id == definition_id
    assert command.expected_selected_scenario_id is None
    assert service.select.await_args.args == (session,)
    assert service.select.await_args.kwargs["user_id"] == principal.user_id


def test_select_requires_explicit_nullable_target(
    client: TestClient,
    scenario_dependencies,
) -> None:
    service, _, _, _ = scenario_dependencies
    response = client.post(
        f"/api/v1/scenario-simulations/{RUN.id}/select",
        headers=_headers(),
        json={},
    )
    assert response.status_code == 422
    service.select.assert_not_awaited()


def test_regenerate_creates_a_new_run_from_stored_server_evidence(
    client: TestClient,
    scenario_dependencies,
) -> None:
    service, _, session, principal = scenario_dependencies
    service.regenerate.return_value = RUN

    response = client.post(
        f"/api/v1/scenario-simulations/{RUN.id}/regenerate",
        headers=_headers(),
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(RUN.id)
    service.regenerate.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        run_id=RUN.id,
    )


@pytest.mark.parametrize(
    ("method", "path", "service_method", "status_code"),
    [
        ("get", f"/api/v1/scenario-simulations/{RUN.id}", "get", 404),
        (
            "post",
            f"/api/v1/scenario-simulations/{RUN.id}/select",
            "select",
            409,
        ),
        ("post", "/api/v1/scenario-simulations", "simulate", 429),
    ],
)
def test_routes_preserve_safe_application_errors(
    client: TestClient,
    scenario_dependencies,
    method: str,
    path: str,
    service_method: str,
    status_code: int,
) -> None:
    service, _, _, _ = scenario_dependencies
    target = getattr(service, service_method)
    target.side_effect = ApplicationError(
        code=f"scenario_test_{status_code}",
        message="Safe scenario operation failure.",
        status_code=status_code,
    )
    kwargs = {}
    if service_method == "simulate":
        kwargs["json"] = _payload()
    if service_method == "select":
        kwargs["json"] = {
            "scenario_definition_id": str(RUN.definitions[0].id),
            "expected_selected_scenario_id": None,
        }

    response = getattr(client, method)(path, headers=_headers(), **kwargs)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == f"scenario_test_{status_code}"


def test_all_scenario_routes_require_authentication(client: TestClient) -> None:
    operations = (
        ("post", "/api/v1/scenario-simulations", {"json": _payload()}),
        ("get", "/api/v1/scenario-simulations", {}),
        ("get", f"/api/v1/scenario-simulations/{RUN.id}", {}),
        ("get", f"/api/v1/scenario-simulations/{RUN.id}/compare", {}),
        (
            "post",
            f"/api/v1/scenario-simulations/{RUN.id}/select",
            {"json": {"scenario_definition_id": None}},
        ),
        (
            "post",
            f"/api/v1/scenario-simulations/{RUN.id}/regenerate",
            {},
        ),
    )
    for method, path, kwargs in operations:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401


def test_openapi_freezes_six_strict_authenticated_operations(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    expected = {
        ("/api/v1/scenario-simulations", "post", "simulate_scenarios"),
        ("/api/v1/scenario-simulations", "get", "list_scenario_simulations"),
        (
            "/api/v1/scenario-simulations/{simulation_id}",
            "get",
            "get_scenario_simulation",
        ),
        (
            "/api/v1/scenario-simulations/{simulation_id}/compare",
            "get",
            "compare_scenario_simulation",
        ),
        (
            "/api/v1/scenario-simulations/{simulation_id}/select",
            "post",
            "select_scenario_simulation",
        ),
        (
            "/api/v1/scenario-simulations/{simulation_id}/regenerate",
            "post",
            "regenerate_scenario_simulation",
        ),
    }
    for path, method, operation_id in expected:
        operation = paths[path][method]
        assert operation["operationId"] == operation_id
        assert operation["security"] == [{"HTTPBearer": []}]

    schemas = document["components"]["schemas"]
    request = schemas["ScenarioSimulationDraftRequest"]
    assert set(request["properties"]) == {"source_plan_id", "scenarios"}
    assert request["additionalProperties"] is False
    selection = schemas["ScenarioSelectionRequest"]
    assert set(selection["properties"]) == {
        "scenario_definition_id",
        "expected_selected_scenario_id",
    }
    assert selection["required"] == ["scenario_definition_id"]
    assert selection["additionalProperties"] is False
    response = schemas["ScenarioSimulationRunResponse"]
    assert "user_id" not in response["properties"]
    assert "raw_samples" not in response["properties"]
