"""Contract tests for the approved Phase 7 classification boundary."""

from pathlib import Path

from falcon_api.schemas.classification import (
    ClassificationBatchRequest,
    ClassificationResult,
    TransactionCategoryCorrectionRequest,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMPLEMENTATION_DOCUMENT = (
    _REPOSITORY_ROOT
    / "docs"
    / "classification"
    / "PHASE_7_IMPLEMENTATION.md"
)


def test_public_writes_exclude_server_owned_prediction_fields() -> None:
    batch = set(ClassificationBatchRequest.model_json_schema()["properties"])
    correction = set(
        TransactionCategoryCorrectionRequest.model_json_schema()["properties"]
    )

    assert batch == {"transaction_ids"}
    assert correction == {"category_id"}
    for private_field in {
        "user_id",
        "confidence",
        "decision",
        "source",
        "model_version",
        "ruleset_version",
        "taxonomy_version",
    }:
        assert private_field not in batch
        assert private_field not in correction


def test_prediction_response_excludes_features_and_ownership() -> None:
    properties = set(ClassificationResult.model_json_schema()["properties"])

    assert "user_id" not in properties
    assert "raw_description" not in properties
    assert "feature_vector" not in properties
    assert "model_path" not in properties


def test_phase_document_defines_the_approved_classification_contract() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    required_statements = (
        "authenticated principal",
        "taxonomy version",
        "2026.1",
        "macro-f1",
        "abstain",
        "low-confidence",
        "manual transactions",
        "csv",
        "digital pdf",
        "cross-user",
        "user correction",
        "raw transaction descriptions",
        "checkpoint 7.1",
        "checkpoint 7.8",
        "phase 6",
        "phase 8",
    )

    for statement in required_statements:
        assert statement in content
