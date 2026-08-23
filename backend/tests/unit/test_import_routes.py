"""API contracts for authenticated statement import operations."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from falcon_api.api.routes.auth import current_principal_service_from
from falcon_api.api.routes.imports import import_service_from
from falcon_api.auth.principal import (
    AuthenticatedPrincipal,
    CurrentPrincipalService,
)
from falcon_api.imports import ImportService
from falcon_api.infrastructure.database import get_database_session
from falcon_api.models.enums import ImportDateOrder, ImportStatus
from falcon_api.models.import_job import ImportJob, ImportJobIssue
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


_TOKEN = "signed-import-access-token"
_NOW = datetime(2026, 8, 20, 15, 30, tzinfo=UTC)
_CSV = (
    b"Date,Description,Amount\n"
    b"20/08/2026,Salary,50000\n"
)


@pytest.fixture
def import_dependencies(
    client: TestClient,
) -> Iterator[
    tuple[AsyncMock, AsyncMock, AsyncMock, AuthenticatedPrincipal]
]:
    """Override persistence, authentication, and import services."""
    principal = AuthenticatedPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email="import-user@example.com",
        display_name="Import User",
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=_NOW,
    )
    principal_service = Mock(spec=CurrentPrincipalService)
    principal_service.authenticate = AsyncMock(return_value=principal)
    import_service = AsyncMock(spec=ImportService)
    session = AsyncMock(spec=AsyncSession)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    client.app.dependency_overrides[get_database_session] = session_override
    client.app.dependency_overrides[
        current_principal_service_from
    ] = lambda: principal_service
    client.app.dependency_overrides[
        import_service_from
    ] = lambda: import_service

    try:
        yield import_service, principal_service, session, principal
    finally:
        client.app.dependency_overrides.clear()


def _job(principal: AuthenticatedPrincipal) -> ImportJob:
    account_id = uuid4()
    job = ImportJob(
        id=uuid4(),
        user_id=principal.user_id,
        account_id=account_id,
        source_type="csv",
        original_filename="statement.csv",
        file_fingerprint="a" * 64,
        date_order=ImportDateOrder.DAY_FIRST,
        header_row=1,
        sheet_name=None,
        status=ImportStatus.PARTIAL,
        started_at=_NOW,
        completed_at=_NOW,
        accepted_count=1,
        rejected_count=1,
        failure_summary=None,
        issues_truncated=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    job.issues = [
        ImportJobIssue(
            id=uuid4(),
            user_id=principal.user_id,
            import_job_id=job.id,
            row_number=3,
            code="zero_amount",
            message="The amount must not be zero.",
            created_at=_NOW,
            updated_at=_NOW,
        )
    ]
    return job


def _upload(
    client: TestClient,
    *,
    account_id,
    data: dict[str, str] | None = None,
    content: bytes = _CSV,
    filename: str = "statement.csv",
    content_type: str = "text/csv",
):
    return client.post(
        "/api/v1/imports",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        data=data
        or {
            "account_id": str(account_id),
            "source_type": "csv",
            "date_order": "day_first",
            "header_row": "1",
        },
        files={"file": (filename, content, content_type)},
    )


def test_upload_uses_authenticated_owner_timezone_and_bounded_content(
    client: TestClient,
    import_dependencies,
) -> None:
    service, principal_service, session, principal = import_dependencies
    job = _job(principal)
    service.process.return_value = job

    response = _upload(client, account_id=job.account_id)

    assert response.status_code == 201
    assert response.json() == {
        "id": str(job.id),
        "account_id": str(job.account_id),
        "source_type": "csv",
        "original_filename": "statement.csv",
        "status": "partial",
        "accepted_count": 1,
        "rejected_count": 1,
        "issues": [
            {
                "row_number": 3,
                "code": "zero_amount",
                "message": "The amount must not be zero.",
            }
        ],
        "issues_truncated": False,
        "adapter_name": None,
        "balance_reconciled": None,
        "started_at": "2026-08-20T15:30:00Z",
        "completed_at": "2026-08-20T15:30:00Z",
        "created_at": "2026-08-20T15:30:00Z",
        "updated_at": "2026-08-20T15:30:00Z",
    }
    assert "file_fingerprint" not in response.json()
    assert "failure_summary" not in response.json()
    principal_service.authenticate.assert_awaited_once_with(
        session, token=_TOKEN
    )
    call = service.process.await_args
    assert call.args == (session,)
    assert call.kwargs["user_id"] == principal.user_id
    assert call.kwargs["timezone"] == principal.timezone
    command = call.kwargs["command"]
    assert command.filename == "statement.csv"
    assert command.content_type == "text/csv"
    assert command.content == _CSV
    assert command.options.account_id == job.account_id
    assert command.file_password is None


def test_pdf_upload_passes_ephemeral_password_without_echoing_it(
    client: TestClient,
    import_dependencies,
) -> None:
    service, _, _, principal = import_dependencies
    job = _job(principal)
    job.source_type = "bank_statement"
    job.original_filename = "statement.pdf"
    job.adapter_name = "generic_digital_pdf_v1"
    job.balance_reconciled = True
    service.process.return_value = job

    response = _upload(
        client,
        account_id=job.account_id,
        data={
            "account_id": str(job.account_id),
            "source_type": "bank_statement",
            "file_password": "private-password",
        },
        content=b"%PDF-private-test",
        filename="statement.pdf",
        content_type="application/pdf",
    )

    assert response.status_code == 201
    command = service.process.await_args.kwargs["command"]
    assert command.file_password == "private-password"
    assert "private-password" not in response.text
    assert response.json()["adapter_name"] == "generic_digital_pdf_v1"
    assert response.json()["balance_reconciled"] is True


def test_status_read_is_owner_scoped(
    client: TestClient,
    import_dependencies,
) -> None:
    service, _, session, principal = import_dependencies
    job = _job(principal)
    service.get_job.return_value = job

    response = client.get(
        f"/api/v1/imports/{job.id}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )

    assert response.status_code == 200
    service.get_job.assert_awaited_once_with(
        session,
        user_id=principal.user_id,
        job_id=job.id,
    )


@pytest.mark.parametrize(
    ("overrides", "expected_field"),
    [
        ({"source_type": "pdf"}, "body.source_type"),
        ({"header_row": "0"}, "body.header_row"),
        ({"account_id": "not-a-uuid"}, "body.account_id"),
    ],
)
def test_upload_rejects_invalid_form_metadata_before_service(
    client: TestClient,
    import_dependencies,
    overrides: dict[str, str],
    expected_field: str,
) -> None:
    service, _, _, _ = import_dependencies
    data = {
        "account_id": str(uuid4()),
        "source_type": "csv",
        "date_order": "day_first",
        "header_row": "1",
        **overrides,
    }

    response = _upload(client, account_id=uuid4(), data=data)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    fields = {
        detail["field"]
        for detail in response.json()["error"].get("details", [])
    }
    assert expected_field in fields
    service.process.assert_not_awaited()


def test_upload_rejects_csv_worksheet_selection(
    client: TestClient,
    import_dependencies,
) -> None:
    service, _, _, _ = import_dependencies

    response = _upload(
        client,
        account_id=uuid4(),
        data={
            "account_id": str(uuid4()),
            "source_type": "csv",
            "sheet_name": "Transactions",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    service.process.assert_not_awaited()


@pytest.mark.parametrize("field", ["user_id", "status", "file_fingerprint"])
def test_upload_rejects_server_owned_form_fields(
    client: TestClient,
    import_dependencies,
    field: str,
) -> None:
    service, _, _, _ = import_dependencies
    data = {
        "account_id": str(uuid4()),
        "source_type": "csv",
        field: "server-owned-value",
    }

    response = _upload(client, account_id=uuid4(), data=data)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"][0]["field"] == (
        f"body.{field}"
    )
    service.process.assert_not_awaited()


def test_upload_rejects_oversized_file_before_service(
    client: TestClient,
    import_dependencies,
) -> None:
    service, _, _, _ = import_dependencies

    response = _upload(
        client,
        account_id=uuid4(),
        content=b"x" * (10 * 1024 * 1024 + 1),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "import_file_too_large"
    service.process.assert_not_awaited()


def test_import_routes_require_authentication(client: TestClient) -> None:
    upload = client.post(
        "/api/v1/imports",
        data={"account_id": str(uuid4()), "source_type": "csv"},
        files={"file": ("statement.csv", _CSV, "text/csv")},
    )
    status_response = client.get(f"/api/v1/imports/{uuid4()}")

    assert upload.status_code == 401
    assert status_response.status_code == 401
    assert upload.json()["error"]["code"] == "invalid_access_token"
    assert status_response.json()["error"]["code"] == "invalid_access_token"
