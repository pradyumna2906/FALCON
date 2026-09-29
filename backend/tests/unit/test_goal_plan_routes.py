"""Authenticated public API contracts for persistent goal plans."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.goal_plans import goal_plan_service_from
from falcon_api.auth.principal import AuthenticatedPrincipal, CurrentPrincipalService
from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning import MultiGoalOptimizationService
from falcon_api.infrastructure.database import get_database_session
from falcon_api.models.enums import GoalPlanEventSource, GoalPlanStatus
from falcon_api.models.goal_plan import GoalPlanEvent, GoalPlanRun
from goal_plan_test_data import NOW, transient_goal_plan_run


_TOKEN = "signed-goal-plan-access-token"


@pytest.fixture
def goal_plan_dependencies(client: TestClient):
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="planner@example.com",
        display_name="Planner",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    plan_service = AsyncMock(spec=MultiGoalOptimizationService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[current_principal_service_from] = (
        lambda: principal_service
    )
    client.app.dependency_overrides[goal_plan_service_from] = lambda: plan_service
    try:
        yield plan_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _mark(run: GoalPlanRun, status: GoalPlanStatus) -> GoalPlanRun:
    run.events.append(
        GoalPlanEvent(
            user_id=run.user_id,
            plan_run_id=run.id,
            previous_status=GoalPlanStatus.GENERATED.value,
            status=status.value,
            source=GoalPlanEventSource.USER,
            occurred_at=NOW,
            successor_plan_id=None,
            reason_code=f"user_{status.value}_plan",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return run


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


def test_generate_uses_authenticated_owner_defaults_and_hides_owner(
    client: TestClient,
    goal_plan_dependencies,
) -> None:
    service, principal_service, session, principal = goal_plan_dependencies
    run = transient_goal_plan_run(user_id=principal.user_id)
    service.generate.return_value = run

    response = client.post("/api/v1/goal-plans", headers=_headers(), json={})

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] == str(run.id)
    assert payload["status"] == "generated"
    assert payload["strategy"] == "guarded_greedy_fallback"
    assert len(payload["outcomes"]) == 1
    assert len(payload["periods"]) == 2
    assert "user_id" not in repr(payload)
    command = service.generate.await_args.kwargs["command"]
    assert command.currency == principal.default_currency
    assert command.trusted_timezone == principal.timezone
    assert service.generate.await_args.kwargs["user_id"] == principal.user_id
    assert service.generate.await_args.args == (session,)
    principal_service.authenticate.assert_awaited_once_with(
        session,
        token=_TOKEN,
    )


def test_generate_normalizes_explicit_currency(
    client: TestClient,
    goal_plan_dependencies,
) -> None:
    service, _, _, principal = goal_plan_dependencies
    service.generate.return_value = transient_goal_plan_run(
        user_id=principal.user_id
    )

    response = client.post(
        "/api/v1/goal-plans",
        headers=_headers(),
        json={"currency": " usd "},
    )

    assert response.status_code == 201
    assert service.generate.await_args.kwargs["command"].currency == "USD"


@pytest.mark.parametrize(
    "payload",
    [
        {"owner_id": "10000000-0000-4000-8000-000000000001"},
        {"planning_cutoff_at": "2026-09-15T12:00:00Z"},
        {"optimization_algorithm": "client-controlled"},
        {"currency": "RUPEE"},
    ],
)
def test_generate_rejects_server_owned_or_unbounded_inputs(
    client: TestClient,
    goal_plan_dependencies,
    payload,
) -> None:
    service, _, _, _ = goal_plan_dependencies

    response = client.post(
        "/api/v1/goal-plans",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 422
    service.generate.assert_not_awaited()


def test_list_is_owner_scoped_bounded_and_returns_summaries(
    client: TestClient,
    goal_plan_dependencies,
) -> None:
    service, _, session, principal = goal_plan_dependencies
    run = transient_goal_plan_run(user_id=principal.user_id)
    service.list_recent.return_value = (run,)

    response = client.get(
        "/api/v1/goal-plans?limit=25",
        headers=_headers(),
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == str(run.id)
    assert "outcomes" not in item
    assert "periods" not in item
    service.list_recent.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        limit=25,
    )


@pytest.mark.parametrize("limit", [0, 101])
def test_list_rejects_out_of_bounds_limit(
    client: TestClient,
    goal_plan_dependencies,
    limit,
) -> None:
    service, _, _, _ = goal_plan_dependencies

    response = client.get(
        f"/api/v1/goal-plans?limit={limit}",
        headers=_headers(),
    )

    assert response.status_code == 422
    service.list_recent.assert_not_awaited()


def test_get_uses_authenticated_owner_and_returns_complete_plan(
    client: TestClient,
    goal_plan_dependencies,
) -> None:
    service, _, session, principal = goal_plan_dependencies
    run = transient_goal_plan_run(user_id=principal.user_id)
    service.get.return_value = run

    response = client.get(
        f"/api/v1/goal-plans/{run.id}",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == run.snapshot_id
    service.get.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        plan_id=run.id,
    )


@pytest.mark.parametrize(
    ("action", "status"),
    [("approve", GoalPlanStatus.APPROVED), ("reject", GoalPlanStatus.REJECTED)],
)
def test_decision_routes_use_owner_and_append_only_service(
    client: TestClient,
    goal_plan_dependencies,
    action,
    status,
) -> None:
    service, _, session, principal = goal_plan_dependencies
    run = _mark(
        transient_goal_plan_run(user_id=principal.user_id),
        status,
    )
    getattr(service, action).return_value = run

    response = client.post(
        f"/api/v1/goal-plans/{run.id}/{action}",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == status.value
    getattr(service, action).assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        plan_id=run.id,
    )


def test_regenerate_uses_principal_timezone_and_returns_new_version(
    client: TestClient,
    goal_plan_dependencies,
) -> None:
    service, _, session, principal = goal_plan_dependencies
    run = transient_goal_plan_run(user_id=principal.user_id)
    service.regenerate.return_value = run

    response = client.post(
        f"/api/v1/goal-plans/{uuid4()}/regenerate",
        headers=_headers(),
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(run.id)
    call = service.regenerate.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["trusted_timezone"] == principal.timezone


@pytest.mark.parametrize(
    ("method", "path", "error", "expected"),
    [
        (
            "get",
            "/api/v1/goal-plans/10000000-0000-4000-8000-000000000001",
            ApplicationError(
                code="goal_plan_not_found",
                message="The requested goal plan was not found.",
                status_code=404,
            ),
            404,
        ),
        (
            "post",
            "/api/v1/goal-plans/10000000-0000-4000-8000-000000000001/approve",
            ApplicationError(
                code="goal_plan_transition_conflict",
                message="The goal plan lifecycle does not permit this operation.",
                status_code=409,
            ),
            409,
        ),
        (
            "post",
            "/api/v1/goal-plans",
            ApplicationError(
                code="goal_plan_unavailable",
                message="The available evidence could not produce a safe goal plan.",
                status_code=422,
            ),
            422,
        ),
    ],
)
def test_routes_preserve_safe_application_errors(
    client: TestClient,
    goal_plan_dependencies,
    method,
    path,
    error,
    expected,
) -> None:
    service, _, _, _ = goal_plan_dependencies
    target = (
        service.get
        if method == "get"
        else service.generate
        if path == "/api/v1/goal-plans"
        else service.approve
    )
    target.side_effect = error

    response = getattr(client, method)(
        path,
        headers=_headers(),
        **({"json": {}} if path == "/api/v1/goal-plans" else {}),
    )

    assert response.status_code == expected
    assert response.json()["error"]["code"] == error.code


def test_goal_plan_routes_require_authentication(client: TestClient) -> None:
    for method, path, kwargs in (
        ("post", "/api/v1/goal-plans", {"json": {}}),
        ("get", "/api/v1/goal-plans", {}),
        (
            "get",
            "/api/v1/goal-plans/10000000-0000-4000-8000-000000000001",
            {},
        ),
    ):
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401


def test_openapi_freezes_six_goal_plan_operations_and_minimal_request(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    expected = {
        ("/api/v1/goal-plans", "post", "generate_goal_plan"),
        ("/api/v1/goal-plans", "get", "list_goal_plans"),
        ("/api/v1/goal-plans/{plan_id}", "get", "get_goal_plan"),
        (
            "/api/v1/goal-plans/{plan_id}/approve",
            "post",
            "approve_goal_plan",
        ),
        (
            "/api/v1/goal-plans/{plan_id}/reject",
            "post",
            "reject_goal_plan",
        ),
        (
            "/api/v1/goal-plans/{plan_id}/regenerate",
            "post",
            "regenerate_goal_plan",
        ),
    }
    for path, method, operation_id in expected:
        assert paths[path][method]["operationId"] == operation_id

    request_schema = schema["components"]["schemas"][
        "GoalPlanGenerationRequest"
    ]
    assert set(request_schema["properties"]) == {"currency"}
    assert request_schema["additionalProperties"] is False
