"""Unit tests for strict statement-import API schemas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from falcon_api.models.enums import ImportSourceType, ImportStatus
from falcon_api.schemas.imports import (
    ImportIssueCode,
    ImportJobResponse,
    ImportRowIssue,
    StatementImportOptions,
)
from pydantic import ValidationError


def test_csv_options_accept_safe_defaults() -> None:
    options = StatementImportOptions(
        account_id=uuid4(),
        source_type="csv",
    )

    assert options.source_type is ImportSourceType.CSV
    assert options.date_order == "day_first"
    assert options.header_row == 1
    assert options.sheet_name is None


def test_excel_options_normalize_a_worksheet_name() -> None:
    options = StatementImportOptions(
        account_id=uuid4(),
        source_type="excel",
        sheet_name="  Transactions  ",
        header_row=3,
    )

    assert options.sheet_name == "Transactions"
    assert options.header_row == 3


def test_blank_excel_sheet_name_is_treated_as_omitted() -> None:
    options = StatementImportOptions(
        account_id=uuid4(),
        source_type="excel",
        sheet_name="   ",
    )

    assert options.sheet_name is None


def test_csv_options_reject_excel_only_sheet_selection() -> None:
    with pytest.raises(ValidationError, match="Excel imports"):
        StatementImportOptions(
            account_id=uuid4(),
            source_type="csv",
            sheet_name="Transactions",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"source_type": "bank_statement"},
        {"source_type": "pdf"},
        {"source_type": "csv", "header_row": 0},
        {"source_type": "excel", "header_row": 51},
    ],
)
def test_options_reject_deferred_sources_and_unsafe_bounds(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        StatementImportOptions(account_id=uuid4(), **payload)  # type: ignore[arg-type]


def test_options_reject_server_owned_import_fields() -> None:
    with pytest.raises(ValidationError) as info:
        StatementImportOptions(
            account_id=uuid4(),
            source_type="csv",
            user_id=uuid4(),
            status="completed",
            file_fingerprint="secret",
        )

    locations = {error["loc"] for error in info.value.errors()}
    assert ("user_id",) in locations
    assert ("status",) in locations
    assert ("file_fingerprint",) in locations


def test_row_issue_is_bounded_and_contains_no_raw_value_field() -> None:
    issue = ImportRowIssue(
        row_number=8,
        code=ImportIssueCode.INVALID_AMOUNT,
        message="The amount is invalid.",
    )

    assert issue.row_number == 8
    assert "raw_value" not in issue.model_json_schema()["properties"]

    with pytest.raises(ValidationError):
        ImportRowIssue(
            row_number=0,
            code=ImportIssueCode.INVALID_AMOUNT,
            message="The amount is invalid.",
        )


def test_job_response_excludes_owner_fingerprint_and_failure_details() -> None:
    properties = set(ImportJobResponse.model_json_schema()["properties"])

    assert "user_id" not in properties
    assert "file_fingerprint" not in properties
    assert "failure_summary" not in properties


def test_job_response_enforces_issue_and_count_bounds() -> None:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    response = ImportJobResponse(
        id=uuid4(),
        account_id=uuid4(),
        source_type="csv",
        original_filename="statement.csv",
        status=ImportStatus.PARTIAL,
        accepted_count=10,
        rejected_count=1,
        issues=(
            ImportRowIssue(
                row_number=12,
                code="missing_date",
                message="The transaction date is required.",
            ),
        ),
        issues_truncated=False,
        started_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )

    assert response.accepted_count == 10
    assert response.issues[0].code is ImportIssueCode.MISSING_DATE

@pytest.mark.parametrize(
    "filename",
    ["../statement.csv", "folder/statement.csv", "folder\\statement.csv"],
)
def test_job_response_rejects_unsafe_filenames(filename: str) -> None:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="safe base name"):
        ImportJobResponse(
            id=uuid4(),
            account_id=uuid4(),
            source_type="csv",
            original_filename=filename,
            status="failed",
            accepted_count=0,
            rejected_count=0,
            issues=(),
            issues_truncated=False,
            started_at=now,
            completed_at=now,
            created_at=now,
            updated_at=now,
        )
