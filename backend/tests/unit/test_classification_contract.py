"""Contract tests for the approved Phase 7 classification boundary."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
    feature_record,
)
from falcon_api.classification.dataset import (
    DatasetSourceKind,
    load_classification_dataset,
)
from falcon_api.classification.taxonomy import ClassificationSubcategoryCode
from falcon_api.models.enums import TransactionType
from falcon_api.schemas.classification import (
    ClassificationBatchRequest,
    ClassificationResult,
    MerchantMemoryWriteRequest,
    TransactionCategoryCorrectionRequest,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMPLEMENTATION_DOCUMENT = (
    _REPOSITORY_ROOT
    / "docs"
    / "classification"
    / "PHASE_7_IMPLEMENTATION.md"
)
_SYNTHETIC_DATASET_DIRECTORY = (
    _REPOSITORY_ROOT / "data" / "synthetic" / "classification"
)
_EVALUATION_REPORT = (
    _REPOSITORY_ROOT
    / "ml"
    / "reports"
    / "classification_evaluation_2026_1.json"
)


def test_public_writes_exclude_server_owned_prediction_fields() -> None:
    batch = set(ClassificationBatchRequest.model_json_schema()["properties"])
    correction = set(
        TransactionCategoryCorrectionRequest.model_json_schema()["properties"]
    )
    memory = set(MerchantMemoryWriteRequest.model_json_schema()["properties"])

    assert batch == {"transaction_ids"}
    assert correction == {"category_id"}
    assert memory == {"merchant_name", "category_id"}
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
        assert private_field not in memory


def test_prediction_response_excludes_features_and_ownership() -> None:
    properties = set(ClassificationResult.model_json_schema()["properties"])

    assert "user_id" not in properties
    assert "raw_description" not in properties
    assert "feature_vector" not in properties
    assert "model_path" not in properties


def test_model_record_excludes_ownership_source_references_and_exact_amount() -> None:
    features = build_classification_features(
        TransactionFeatureInput(
            description="UPI/123456789012/SWIGGY/person@okbank",
            merchant_name=None,
            transaction_type=TransactionType.EXPENSE,
            signed_amount=Decimal("-849.99"),
            transaction_date=date(2026, 8, 23),
            account_currency="INR",
        )
    )
    record = feature_record(features)

    assert "user_id" not in record
    assert "source_type" not in record
    assert "source_reference" not in record
    assert "signed_amount" not in record
    assert "123456789012" not in str(record)
    assert "person@okbank" not in str(record)


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
        "checkpoint 7.2",
        "checkpoint 7.3",
        "checkpoint 7.4",
        "checkpoint 7.5",
        "checkpoint 7.8",
        "phase 7 status: complete",
        "classification_operation_completed",
        "100 transactions",
        "feature schema version",
        "exact normalized aliases",
        "explicit conflict",
        "production_eligible",
        "group-aware",
        "classifier_unavailable",
        "thread-safe lazy",
        "phase 6",
        "phase 8",
    )

    for statement in required_statements:
        assert statement in content


def test_published_dataset_and_model_evidence_are_integrity_checked() -> None:
    records = (
        _SYNTHETIC_DATASET_DIRECTORY / "transactions_2026_1.jsonl"
    ).read_text(encoding="utf-8")
    manifest = json.loads(
        (_SYNTHETIC_DATASET_DIRECTORY / "manifest_2026_1.json").read_text(
            encoding="utf-8"
        )
    )
    dataset = load_classification_dataset(records, manifest)
    report = json.loads(_EVALUATION_REPORT.read_text(encoding="utf-8"))

    assert dataset.manifest.source_kind is DatasetSourceKind.SYNTHETIC
    assert dataset.manifest.record_count == 864
    assert dataset.manifest.group_count == 288
    assert len(dataset.manifest.label_counts) == len(ClassificationSubcategoryCode)
    assert report["dataset_sha256"] == dataset.manifest.records_sha256
    assert report["dataset_version"] == dataset.manifest.dataset_version
    assert report["production_eligible"] is False
    assert {item["candidate"] for item in report["evaluations"]} == {
        "majority_baseline",
        "keyword_rule_baseline",
        "tfidf_logistic_regression",
        "tfidf_calibrated_linear_svm",
    }
