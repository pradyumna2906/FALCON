"""Authenticated public API contracts for Phase 10 goals."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.goals import (
    contribution_service_from,
    goal_service_from,
    planning_snapshot_service_from,
)
from falcon_api.auth.principal import AuthenticatedPrincipal, CurrentPrincipalService
from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning import (
    ContributionService,
    GoalPlanningSnapshotService,
    GoalService,
    calculate_goal_progress,
)
from falcon_api.goal_planning.capacity import SavingsCapacityPlan, SavingsCapacityPoint
from falcon_api.goal_planning.snapshot import (
    GoalPlanningSnapshot,
    PlanningBudgetEvidence,
    PlanningFinancialEvidence,
    PlanningProvenance,
)
from falcon_api.infrastructure.database import get_database_session
from falcon_api.models.enums import (
    ContributionSourceType,
    GoalPriority,
    GoalStatus,
    GoalType,
)
from falcon_api.models.planning import Goal, GoalContribution


_TOKEN = "signed-goal-access-token"
_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


@pytest.fixture
def goal_dependencies(
    client: TestClient,
) -> tuple[AsyncMock, AsyncMock, AsyncMock, AuthenticatedPrincipal]:
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="goal-owner@example.com",
        display_name="Goal Owner",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    goal_service = AsyncMock(spec=GoalService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: principal_service
    client.app.dependency_overrides[goal_service_from] = lambda: goal_service
    try:
        yield goal_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


@pytest.fixture
def planning_dependencies(client: TestClient):
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="planner@example.com",
        display_name="Planner",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    contribution_service = AsyncMock(spec=ContributionService)
    snapshot_service = AsyncMock(spec=GoalPlanningSnapshotService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: principal_service
    client.app.dependency_overrides[
        contribution_service_from
    ] = lambda: contribution_service
    client.app.dependency_overrides[
        planning_snapshot_service_from
    ] = lambda: snapshot_service
    try:
        yield contribution_service, snapshot_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _goal(*, user_id=None, status: GoalStatus = GoalStatus.ACTIVE) -> Goal:
    return Goal(
        id=uuid4(),
        user_id=user_id or uuid4(),
        name="Education Fund",
        goal_type=GoalType.EDUCATION,
        target_amount=Decimal("200000.0000"),
        starting_amount=Decimal("25000.0000"),
        currency="INR",
        target_date=date(2028, 6, 1),
        priority=GoalPriority.HIGH,
        status=status,
        description="Semester fees",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _payload() -> dict[str, object]:
    return {
        "name": "Education Fund",
        "goal_type": "education",
        "target_amount": "200000.0000",
        "starting_amount": "25000.0000",
        "target_date": "2028-06-01",
        "priority": "high",
        "description": "Semester fees",
    }


def _assert_public_goal(response, goal: Goal) -> None:
    assert response.json() == {
        "id": str(goal.id),
        "name": "Education Fund",
        "goal_type": "education",
        "target_amount": "200000.0000",
        "starting_amount": "25000.0000",
        "currency": "INR",
        "target_date": "2028-06-01",
        "priority": "high",
        "status": goal.status.value,
        "description": "Semester fees",
        "created_at": "2026-09-14T12:00:00Z",
        "updated_at": "2026-09-14T12:00:00Z",
    }
    assert "user_id" not in response.json()


def test_create_uses_authenticated_owner_timezone_and_currency(
    client: TestClient,
    goal_dependencies,
) -> None:
    service, principal_service, session, principal = goal_dependencies
    goal = _goal(user_id=principal.user_id)
    service.create.return_value = goal

    response = client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_payload(),
    )

    assert response.status_code == 201
    _assert_public_goal(response, goal)
    principal_service.authenticate.assert_awaited_once_with(session, token=_TOKEN)
    call = service.create.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["default_currency"] == "INR"
    assert call.kwargs["trusted_timezone"] == "Asia/Kolkata"
    assert call.kwargs["command"].currency is None


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": str(uuid4())},
        {"status": "completed"},
        {"id": str(uuid4())},
        {"currency": "invalid"},
        {"starting_amount": "200001"},
    ],
)
def test_create_rejects_invalid_or_server_owned_values(
    client: TestClient,
    goal_dependencies,
    extra: dict[str, object],
) -> None:
    service, _, _, _ = goal_dependencies

    response = client.post(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json={**_payload(), **extra},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.create.assert_not_awaited()


def test_list_maps_status_limit_and_public_items(
    client: TestClient,
    goal_dependencies,
) -> None:
    service, _, session, principal = goal_dependencies
    goal = _goal(user_id=principal.user_id)
    service.list.return_value = (goal,)

    response = client.get(
        "/api/v1/goals",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={"status": "active", "limit": "25"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(goal.id)
    assert "user_id" not in response.json()["items"][0]
    service.list.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        status=GoalStatus.ACTIVE,
        limit=25,
    )


def test_get_update_complete_and_cancel_use_owned_identifier(
    client: TestClient,
    goal_dependencies,
) -> None:
    service, _, session, principal = goal_dependencies
    goal = _goal(user_id=principal.user_id)
    service.get.return_value = goal
    service.update.return_value = goal
    service.complete.return_value = goal
    service.cancel.return_value = goal

    headers = {"Authorization": f"Bearer {_TOKEN}"}
    assert client.get(f"/api/v1/goals/{goal.id}", headers=headers).status_code == 200
    update = client.patch(
        f"/api/v1/goals/{goal.id}",
        headers=headers,
        json={"priority": "critical", "description": None},
    )
    assert update.status_code == 200
    assert (
        client.post(f"/api/v1/goals/{goal.id}/complete", headers=headers).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/goals/{goal.id}/cancel", headers=headers).status_code
        == 200
    )

    service.get.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        goal_id=goal.id,
    )
    update_call = service.update.await_args
    assert update_call.kwargs["goal_id"] == goal.id
    assert update_call.kwargs["trusted_timezone"] == principal.timezone
    assert update_call.kwargs["command"].fields == {"priority", "description"}
    service.complete.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        goal_id=goal.id,
    )
    service.cancel.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        goal_id=goal.id,
    )


@pytest.mark.parametrize("payload", [{}, {"priority": None}, {"status": "completed"}])
def test_update_rejects_empty_null_or_server_owned_payload(
    client: TestClient,
    goal_dependencies,
    payload: dict[str, object],
) -> None:
    service, _, _, _ = goal_dependencies

    response = client.patch(
        f"/api/v1/goals/{uuid4()}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.update.assert_not_awaited()


def test_service_errors_keep_private_goal_state_hidden(
    client: TestClient,
    goal_dependencies,
) -> None:
    service, _, _, _ = goal_dependencies
    service.get.side_effect = ApplicationError(
        code="goal_not_found",
        message="The requested goal was not found.",
        status_code=404,
    )

    response = client.get(
        f"/api/v1/goals/{uuid4()}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "goal_not_found"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/goals"),
        ("post", "/api/v1/goals"),
        ("get", f"/api/v1/goals/{uuid4()}"),
        ("patch", f"/api/v1/goals/{uuid4()}"),
        ("post", f"/api/v1/goals/{uuid4()}/complete"),
    ],
)
def test_every_goal_operation_requires_authentication(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(
        method,
        path,
        json=_payload() if method in {"post", "patch"} else None,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_access_token"


def test_openapi_documents_complete_goal_management_contract(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()

    assert set(document["paths"]["/api/v1/goals"]) >= {"get", "post"}
    assert set(document["paths"]["/api/v1/goals/{goal_id}"]) >= {
        "get",
        "patch",
    }
    assert "/api/v1/goals/{goal_id}/complete" in document["paths"]
    assert "/api/v1/goals/{goal_id}/cancel" in document["paths"]
    assert document["paths"]["/api/v1/goals"]["post"]["security"] == [
        {"HTTPBearer": []}
    ]


def test_cors_preflight_allows_goal_patch(client: TestClient) -> None:
    response = client.options(
        f"/api/v1/goals/{uuid4()}",
        headers={
            "Origin": "https://app.falcon.test",
            "Access-Control-Request-Method": "PATCH",
        },
    )

    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def _contribution(*, goal_id, user_id) -> GoalContribution:
    return GoalContribution(
        id=uuid4(),
        user_id=user_id,
        goal_id=goal_id,
        transaction_id=None,
        amount=Decimal("1250.5000"),
        contribution_date=date(2026, 9, 1),
        source_type=ContributionSourceType.MANUAL,
        note="Deposit",
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_contribution_create_list_delete_and_progress_routes(
    client: TestClient,
    planning_dependencies,
) -> None:
    service, _, session, principal = planning_dependencies
    goal = _goal(user_id=principal.user_id)
    contribution = _contribution(
        goal_id=goal.id,
        user_id=principal.user_id,
    )
    service.create.return_value = contribution
    service.list.return_value = (contribution,)
    service.progress.return_value = calculate_goal_progress(
        goal=goal,
        contribution_amount=contribution.amount,
        calculated_on=date(2026, 9, 14),
    )
    headers = {"Authorization": f"Bearer {_TOKEN}"}

    created = client.post(
        f"/api/v1/goals/{goal.id}/contributions",
        headers=headers,
        json={
            "source_type": "manual",
            "amount": "1250.5000",
            "contribution_date": "2026-09-01",
        },
    )
    listed = client.get(
        f"/api/v1/goals/{goal.id}/contributions",
        headers=headers,
    )
    progress = client.get(
        f"/api/v1/goals/{goal.id}/progress",
        headers=headers,
    )
    deleted = client.delete(
        f"/api/v1/goals/{goal.id}/contributions/{contribution.id}",
        headers=headers,
    )

    assert created.status_code == 201
    assert created.json()["amount"] == "1250.5000"
    assert "user_id" not in created.json()
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == str(contribution.id)
    assert progress.status_code == 200
    assert progress.json()["contribution_amount"] == "1250.5000"
    assert deleted.status_code == 204
    service.create.assert_awaited_once()
    service.delete.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        goal_id=goal.id,
        contribution_id=contribution.id,
    )


def test_contribution_request_rejects_mixed_provenance(
    client: TestClient,
    planning_dependencies,
) -> None:
    service, _, _, _ = planning_dependencies

    response = client.post(
        f"/api/v1/goals/{uuid4()}/contributions",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json={
            "source_type": "transaction",
            "amount": "100",
            "transaction_id": str(uuid4()),
            "contribution_date": "2026-09-01",
        },
    )

    assert response.status_code == 422
    service.create.assert_not_awaited()


def test_planning_snapshot_route_uses_principal_context(
    client: TestClient,
    planning_dependencies,
) -> None:
    _, service, session, principal = planning_dependencies
    goal = _goal(user_id=principal.user_id)
    progress = calculate_goal_progress(
        goal=goal,
        contribution_amount=Decimal("1000"),
        calculated_on=date(2026, 9, 14),
    )
    capacity = SavingsCapacityPlan(
        forecast_run_id=uuid4(),
        currency="INR",
        policy_version="2026.1",
        protection_band="95_percent",
        reliability="normal",
        points=(
            SavingsCapacityPoint(
                period_start=date(2026, 10, 1),
                protected_amount=Decimal("500"),
                expected_amount=Decimal("1000"),
                upside_amount=Decimal("1500"),
            ),
        ),
        protected_total=Decimal("500"),
        expected_total=Decimal("1000"),
        upside_total=Decimal("1500"),
    )
    service.build.return_value = GoalPlanningSnapshot(
        snapshot_id="a" * 64,
        contract_version="2026.1",
        cutoff_at=_NOW,
        local_date=date(2026, 9, 14),
        timezone="Asia/Kolkata",
        currency="INR",
        goals=(progress,),
        profile=None,
        finances=PlanningFinancialEvidence(
            liquid_balance=Decimal("50000"),
            liability_account_count=0,
            liability_payment_count=0,
            outstanding_debt=Decimal("0"),
            monthly_debt_payment=Decimal("0"),
            source_last_updated_at=_NOW,
        ),
        budgets=PlanningBudgetEvidence(
            active_budget_count=0,
            budget_with_overall_limit_count=0,
            total_overall_limit=Decimal("0"),
            source_last_updated_at=None,
        ),
        savings_capacity=capacity,
        warnings=(),
        provenance=PlanningProvenance(
            goal_ids=(goal.id,),
            contribution_count=1,
            forecast_run_id=capacity.forecast_run_id,
            source_last_updated_at=_NOW,
        ),
    )

    response = client.get(
        "/api/v1/goal-planning/snapshot",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={"currency": "INR"},
    )

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == "a" * 64
    assert Decimal(
        response.json()["savings_capacity"]["protected_total"]
    ) == Decimal("500")
    service.build.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        currency="INR",
        trusted_timezone=principal.timezone,
    )


def test_openapi_documents_batch_2_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/goals/{goal_id}/contributions"]) >= {
        "get",
        "post",
    }
    assert "delete" in paths[
        "/api/v1/goals/{goal_id}/contributions/{contribution_id}"
    ]
    assert "/api/v1/goals/{goal_id}/progress" in paths
    assert "/api/v1/goal-planning/snapshot" in paths


def test_planning_snapshot_rejects_non_iso_currency(
    client: TestClient,
    planning_dependencies,
) -> None:
    _, service, _, _ = planning_dependencies

    response = client.get(
        "/api/v1/goal-planning/snapshot",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        params={"currency": "12R"},
    )

    assert response.status_code == 422
    service.build.assert_not_awaited()
