"""Batch 1 setup validation, authorization, persistence scope and workflows."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.api.routes.auth import current_principal
from falcon_api.api.routes.setup import setup_service_from
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.schemas.setup import (
    AccountMetadataRequest,
    BudgetRequest,
    LiabilityRequest,
    PreferencesRequest,
)
from falcon_api.setup.repository import SetupRepository
from falcon_api.setup.service import SetupService
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


def run(coroutine):
    return asyncio.run(coroutine)


def budget(**changes):
    return dict(
        name="Monthly",
        period_start_date="2026-09-01",
        period_end_date="2026-09-30",
        currency="INR",
        overall_limit="10000",
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": str(uuid4())},
        {"overall_limit": "0"},
        {"currency": "inr"},
        {"period_end_date": "2026-08-01"},
        {"period_end_date": "2028-01-01"},
        {"overall_limit": None},
        {"name": "  "},
        {"overall_limit": "1.00001"},
    ],
)
def test_budget_invalid(changes):
    payload = budget()
    payload.update(changes)
    with pytest.raises(ValidationError):
        BudgetRequest(**payload)


def test_budget_duplicate_categories():
    item = {"category_id": uuid4(), "limit_amount": "12"}
    with pytest.raises(ValidationError):
        BudgetRequest(**budget(limits=[item, item]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", "USD"),
        ("opening_balance", "12"),
        ("account_type", "cash"),
        ("user_id", str(uuid4())),
    ],
)
def test_metadata_rejects_financial_mutation(field, value):
    with pytest.raises(ValidationError):
        AccountMetadataRequest(name="Bank", **{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"annual_interest_rate": "1.1"},
        {"payment_due_day": 32},
        {"outstanding_amount": "-1"},
        {"start_date": "2026-09-01", "maturity_date": "2026-08-01"},
    ],
)
def test_liability_bounds(changes):
    with pytest.raises(ValidationError):
        LiabilityRequest(liability_subtype="loan", **changes)


def test_preferences_contract():
    assert (
        PreferencesRequest(timezone="Asia/Kolkata", default_currency="INR").timezone
        == "Asia/Kolkata"
    )
    with pytest.raises(ValidationError):
        PreferencesRequest(timezone="invalid", default_currency="INR")
    with pytest.raises(ValidationError):
        PreferencesRequest(
            timezone="UTC", default_currency="INR", email="changed@example.com"
        )


@pytest.fixture
def workflow():
    repo = AsyncMock(spec=SetupRepository)
    session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def nested():
        yield

    session.begin_nested = nested
    clock = Mock()
    clock.now.return_value = datetime(2026, 9, 26, tzinfo=UTC)
    return SetupService(repo, clock), repo, session, uuid4(), uuid4()


@pytest.mark.parametrize(
    "operation", ["get_account", "archive_account", "get_budget", "archive_budget"]
)
def test_foreign_and_missing_indistinguishable(workflow, operation):
    service, repo, session, owner, identifier = workflow
    repo.account.return_value = repo.budget.return_value = None
    with pytest.raises(ApplicationError) as exc:
        run(getattr(service, operation)(session, owner, identifier))
    assert exc.value.status_code == 404


def test_account_update_and_archive(workflow):
    service, repo, session, owner, identifier = workflow
    account = SimpleNamespace(archived_at=None)
    repo.account.return_value = account
    run(
        service.update_account(
            session, owner, identifier, AccountMetadataRequest(name="Renamed")
        )
    )
    assert account.name == "Renamed"
    repo.account.assert_awaited_with(session, owner, identifier, lock=True)
    run(service.archive_account(session, owner, identifier))
    first = account.archived_at
    run(service.archive_account(session, owner, identifier))
    assert account.archived_at == first
    with pytest.raises(ApplicationError) as exc:
        run(
            service.update_account(
                session, owner, identifier, AccountMetadataRequest(name="No")
            )
        )
    assert exc.value.status_code == 409


def test_liability_must_match_account(workflow):
    service, repo, session, owner, identifier = workflow
    repo.account.return_value = SimpleNamespace(archived_at=None, account_type="bank")
    with pytest.raises(ApplicationError) as exc:
        run(
            service.put_liability(
                session, owner, identifier, LiabilityRequest(liability_subtype="loan")
            )
        )
    assert exc.value.status_code == 422
    repo.account.return_value.account_type = "loan"
    repo.liability.return_value = None
    result = run(
        service.put_liability(
            session,
            owner,
            identifier,
            LiabilityRequest(liability_subtype="loan", outstanding_amount="10"),
        )
    )
    assert result.user_id == owner and result.account_id == identifier
    assert result.outstanding_amount == 10
    repo.liability.return_value = result
    assert run(service.get_liability(session, owner, identifier)) is result
    assert (
        run(
            service.put_liability(
                session, owner, identifier, LiabilityRequest(liability_subtype="loan")
            )
        )
        is result
    )


def test_budget_creation_and_private_category_rejection(workflow):
    service, repo, session, owner, identifier = workflow
    repo.categories.return_value = ()
    result = run(service.put_budget(session, owner, BudgetRequest(**budget())))
    assert result.user_id == owner and result.name == "Monthly"
    payload = BudgetRequest(
        **budget(limits=[{"category_id": identifier, "limit_amount": "10"}])
    )
    with pytest.raises(ApplicationError) as exc:
        run(service.put_budget(session, owner, payload))
    assert exc.value.status_code == 404
    repo.categories.return_value = (SimpleNamespace(id=identifier),)
    repo.budget.return_value = result
    result.archived_at = None
    assert run(service.put_budget(session, owner, payload, result.id)) is result
    assert len(result.limits) == 1 and result.limits[0].user_id == owner
    run(service.archive_budget(session, owner, result.id))
    assert result.archived_at is not None


def test_preferences_owner_and_values(workflow):
    service, repo, session, owner, _ = workflow
    repo.user.return_value = SimpleNamespace()
    result = run(
        service.preferences(
            session, owner, PreferencesRequest(timezone="UTC", default_currency="USD")
        )
    )
    assert result.timezone == "UTC"
    repo.user.assert_awaited_with(session, owner, lock=True)


@pytest.mark.parametrize(
    "method",
    ["account", "budget", "liability", "user", "budgets", "imports", "categories"],
)
def test_repository_queries_are_owner_scoped(method):
    repo, session, owner, identifier = SetupRepository(), AsyncMock(), uuid4(), uuid4()
    session.scalars.return_value = Mock()
    session.scalars.return_value.all.return_value = []
    args, kwargs = [session, owner], {}
    if method in {"account", "budget", "liability"}:
        args.append(identifier)
    elif method in {"budgets", "imports"}:
        kwargs = {"limit": 20, "offset": 0}
        if method == "budgets":
            kwargs["archived"] = False
    elif method == "categories":
        args.append((identifier,))
    run(getattr(repo, method)(*args, **kwargs))
    mock = (
        session.scalars
        if method in {"budgets", "imports", "categories"}
        else session.scalar
    )
    statement = mock.call_args.args[0]
    assert owner in statement.compile().params.values()
    assert "WHERE" in str(statement)


@pytest.mark.parametrize(
    "path", ["/budgets", "/preferences", "/imports", f"/accounts/{uuid4()}"]
)
def test_setup_requires_authentication(client, path):
    assert client.get("/api/v1" + path).status_code == 401


def test_setup_verification_and_bounds(client):
    owner = SimpleNamespace(user_id=uuid4(), email_verified_at=None)
    service = AsyncMock(spec=SetupService)

    async def session():
        yield AsyncMock()

    client.app.dependency_overrides[current_principal] = lambda: owner
    client.app.dependency_overrides[get_database_session] = session
    client.app.dependency_overrides[setup_service_from] = lambda: service
    try:
        assert client.get("/api/v1/budgets").status_code == 403
        owner.email_verified_at = datetime.now(UTC)
        assert client.get("/api/v1/budgets?limit=101").status_code == 422
        assert client.get("/api/v1/imports?offset=-1").status_code == 422
        response = client.put(
            "/api/v1/preferences",
            json={"timezone": "UTC", "default_currency": "INR", "owner": str(uuid4())},
        )
        assert response.status_code == 422
        service.preferences.return_value = SimpleNamespace(
            display_name=None, timezone="UTC", default_currency="INR"
        )
        assert client.get("/api/v1/preferences").json()["timezone"] == "UTC"
    finally:
        client.app.dependency_overrides.clear()


def test_cors_idempotency_header(client):
    response = client.options(
        "/api/v1/assistant/conversations",
        headers={
            "Origin": "https://app.falcon.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Idempotency-Key,Authorization,Content-Type",
        },
    )
    assert response.status_code == 200


def test_budget_http_lifecycle_serialization_and_pagination(client):
    """Check the actual HTTP contract separately from database service behavior."""
    owner_id, budget_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    owner = SimpleNamespace(user_id=owner_id, email_verified_at=now)
    service = AsyncMock(spec=SetupService)
    service.repository = AsyncMock(spec=SetupRepository)
    row = SimpleNamespace(
        **budget(),
        id=budget_id,
        user_id=owner_id,
        limits=[],
        archived_at=None,
        created_at=now,
        updated_at=now,
    )
    service.put_budget.return_value = service.get_budget.return_value = row
    service.repository.budgets.return_value = [row, row]

    async def session():
        yield AsyncMock()

    client.app.dependency_overrides[current_principal] = lambda: owner
    client.app.dependency_overrides[get_database_session] = session
    client.app.dependency_overrides[setup_service_from] = lambda: service
    try:
        created = client.post("/api/v1/budgets", json=budget())
        assert created.status_code == 201
        assert created.json()["overall_limit"] == "10000"
        assert "user_id" not in created.json()
        assert client.get(f"/api/v1/budgets/{budget_id}").status_code == 200
        assert (
            client.put(f"/api/v1/budgets/{budget_id}", json=budget()).status_code == 200
        )
        listed = client.get("/api/v1/budgets?limit=1&include_archived=true")
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 1
        assert listed.json()["has_more"] is True
        assert service.repository.budgets.call_args.args[1] == owner_id
        assert service.repository.budgets.call_args.kwargs["archived"] is True
        archived = client.delete(f"/api/v1/budgets/{budget_id}")
        assert archived.status_code == 204 and archived.content == b""
        assert service.archive_budget.call_args.args[1:] == (owner_id, budget_id)
    finally:
        client.app.dependency_overrides.clear()
