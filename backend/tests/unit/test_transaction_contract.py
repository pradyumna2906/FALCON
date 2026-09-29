"""Contract tests for the Phase 5 transaction boundary."""

from pathlib import Path

from falcon_api.schemas.transaction import (
    ManualTransactionCreateRequest,
    TransactionResponse,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMPLEMENTATION_DOCUMENT = (
    _REPOSITORY_ROOT
    / "docs"
    / "transactions"
    / "PHASE_5_IMPLEMENTATION.md"
)


def test_manual_transaction_schema_excludes_server_owned_fields() -> None:
    properties = set(
        ManualTransactionCreateRequest.model_json_schema()["properties"]
    )

    assert properties == {
        "account_id",
        "category_id",
        "transaction_type",
        "amount",
        "transaction_date",
        "description",
        "merchant_name",
    }


def test_transaction_response_excludes_ownership_and_deduplication() -> None:
    properties = set(TransactionResponse.model_json_schema()["properties"])

    assert "user_id" not in properties
    assert "external_source_hash" not in properties
    assert "import_job_id" not in properties


def test_phase_document_defines_approved_transaction_contract() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(
        encoding="utf-8"
    ).lower()

    required_statements = (
        "authenticated principal",
        "positive magnitude",
        "cursor",
        "one profile per user",
        "one user-owned account",
        "cross-user",
        "external_source_hash",
        "checkpoint 5.1",
        "phase 6",
    )

    for statement in required_statements:
        assert statement in content
