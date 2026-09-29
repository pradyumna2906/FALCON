"""Contract tests for the Phase 6 statement-import boundary."""

from pathlib import Path

from falcon_api.schemas.imports import (
    ImportJobResponse,
    ImportRowIssue,
    StatementImportOptions,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMPLEMENTATION_DOCUMENT = (
    _REPOSITORY_ROOT / "docs" / "imports" / "PHASE_6_IMPLEMENTATION.md"
)


def test_import_options_expose_only_user_controlled_metadata() -> None:
    properties = set(StatementImportOptions.model_json_schema()["properties"])

    assert properties == {
        "account_id",
        "source_type",
        "date_order",
        "header_row",
        "sheet_name",
    }


def test_import_responses_exclude_private_processing_internals() -> None:
    job_properties = set(ImportJobResponse.model_json_schema()["properties"])
    issue_properties = set(ImportRowIssue.model_json_schema()["properties"])

    assert "user_id" not in job_properties
    assert "file_fingerprint" not in job_properties
    assert "failure_summary" not in job_properties
    assert "raw_row" not in issue_properties
    assert "raw_value" not in issue_properties


def test_phase_document_defines_the_approved_etl_contract() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    required_statements = (
        "authenticated",
        "principal",
        "10 mib",
        "10,000",
        "csv",
        ".xlsx",
        ".pdf",
        "file_password",
        "100 pages",
        "balance_reconciled",
        "formula",
        "one user-owned account",
        "sha-256",
        "external_source_hash",
        "cross-user",
        "raw file",
        "checkpoint 6.1",
        "checkpoint 6.6",
        "phase 7",
    )

    for statement in required_statements:
        assert statement in content
