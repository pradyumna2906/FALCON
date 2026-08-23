"""Tests for the privacy-bounded Phase 7 classification dataset workflow."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from falcon_api.classification.dataset import (
    CLASSIFICATION_DATASET_VERSION,
    ClassificationDataset,
    DatasetRecord,
    DatasetSourceKind,
    LabeledFeatureSample,
    build_classification_dataset,
    load_classification_dataset,
)
from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.models.enums import TransactionType


_SECRET = b"a-private-test-secret-with-at-least-thirty-two-bytes"


def _sample(
    *,
    source_key: str = "private-transaction-1",
    group_key: str = "private-merchant-1",
    description: str = "UPI 123456789012 North Cafe lunch person@okbank",
    merchant_name: str | None = "North Cafe",
    category: ClassificationCategoryCode = ClassificationCategoryCode.FOOD_DINING,
    subcategory: ClassificationSubcategoryCode = (
        ClassificationSubcategoryCode.RESTAURANTS
    ),
) -> LabeledFeatureSample:
    features = build_classification_features(
        TransactionFeatureInput(
            description=description,
            merchant_name=merchant_name,
            transaction_type=TransactionType.EXPENSE,
            signed_amount=Decimal("-725.50"),
            transaction_date=date(2026, 8, 23),
            account_currency="INR",
        )
    )
    return LabeledFeatureSample(
        source_key=source_key,
        group_key=group_key,
        features=features,
        category=category,
        subcategory=subcategory,
        merchant_group=True,
    )


def _dataset(*samples: LabeledFeatureSample) -> ClassificationDataset:
    return build_classification_dataset(
        samples or (_sample(),),
        group_secret=_SECRET,
        source_kind=DatasetSourceKind.SYNTHETIC,
    )


def test_builder_pseudonymizes_private_keys_and_masks_source_references() -> None:
    dataset = _dataset()
    record = dataset.records[0]
    serialized = dataset.records_jsonl()

    assert dataset.manifest.dataset_version == CLASSIFICATION_DATASET_VERSION
    assert dataset.manifest.record_count == 1
    assert dataset.manifest.group_count == 1
    assert dataset.manifest.merchant_group_count == 1
    assert record.record_id.startswith("rec_")
    assert record.group_id.startswith("grp_")
    assert "private-transaction" not in serialized
    assert "private-merchant" not in serialized
    assert "123456789012" not in serialized
    assert "person@okbank" not in serialized


def test_record_reconstructs_features_and_stable_model_text() -> None:
    record = _dataset().records[0]

    assert record.to_features().normalized_description == "north cafe lunch"
    assert record.target == "restaurants"
    assert record.model_text() == (
        "north cafe lunch north cafe type_expense channel_upi amount_small "
        "currency_inr month_8 weekday_6 weekend_1 recurring_0"
    )


def test_manifest_and_jsonl_round_trip_with_integrity_verification() -> None:
    original = _dataset(
        _sample(),
        _sample(
            source_key="private-transaction-2",
            group_key="private-merchant-2",
            description="POS West Bistro dinner",
            merchant_name="West Bistro",
        ),
    )

    restored = load_classification_dataset(
        original.records_jsonl(), original.manifest.to_dict()
    )

    assert restored == original
    assert restored.manifest.records_sha256 == original.manifest.records_sha256


def test_loader_rejects_corruption_and_unknown_record_fields() -> None:
    dataset = _dataset()
    manifest = dataset.manifest.to_dict()
    corrupted = dataset.records_jsonl().replace("north cafe", "south cafe", 1)

    with pytest.raises(ValueError, match="invalid|manifest"):
        load_classification_dataset(corrupted, manifest)

    unknown_field = dataset.records_jsonl().replace(
        '"record_id":', '"unexpected":true,"record_id":', 1
    )
    with pytest.raises(ValueError, match="invalid"):
        load_classification_dataset(unknown_field, manifest)


def test_builder_rejects_duplicate_source_and_duplicate_feature_records() -> None:
    duplicate_source = _sample(
        group_key="different-group",
        description="POS Different Shop dinner",
        merchant_name="Different Shop",
    )
    with pytest.raises(ValueError, match="Duplicate source"):
        _dataset(_sample(), duplicate_source)

    duplicate_feature = _sample(
        source_key="different-source",
        group_key="different-group",
    )
    with pytest.raises(ValueError, match="Duplicate labeled feature"):
        _dataset(_sample(), duplicate_feature)


@pytest.mark.parametrize(
    ("secret", "source_kind", "version", "error"),
    [
        (b"short", DatasetSourceKind.SYNTHETIC, "2026.1", ValueError),
        (_SECRET, "synthetic", "2026.1", TypeError),
        (_SECRET, DatasetSourceKind.SYNTHETIC, "bad version!", ValueError),
    ],
)
def test_builder_rejects_invalid_configuration(
    secret: bytes,
    source_kind: object,
    version: str,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        build_classification_dataset(
            [_sample()],
            group_secret=secret,
            source_kind=source_kind,  # type: ignore[arg-type]
            dataset_version=version,
        )


def test_sample_rejects_invalid_private_keys_feature_type_and_target() -> None:
    with pytest.raises(ValueError, match="source_key"):
        replace(_sample(), source_key=" ")
    with pytest.raises(TypeError, match="features"):
        replace(_sample(), features="unsafe")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="subcategory"):
        replace(
            _sample(),
            category=ClassificationCategoryCode.SHOPPING,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"record_id": "source-id"},
        {"record_id": "grp_" + "a" * 32},
        {"group_id": "merchant-name"},
        {"group_id": "rec_" + "a" * 32},
        {"merchant_group": 1},
        {"taxonomy_version": "old"},
        {"feature_schema_version": "old"},
        {"subcategory": ClassificationSubcategoryCode.SALARY},
    ],
)
def test_dataset_record_rejects_invalid_or_incompatible_values(
    changes: dict[str, object],
) -> None:
    record = _dataset().records[0]

    with pytest.raises((TypeError, ValueError)):
        replace(record, **changes)


def test_dataset_rejects_manifest_that_does_not_match_records() -> None:
    dataset = _dataset()
    invalid_manifest = replace(dataset.manifest, record_count=2)

    with pytest.raises(ValueError, match="manifest"):
        ClassificationDataset(dataset.records, invalid_manifest)


def test_empty_dataset_and_invalid_loader_input_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        build_classification_dataset(
            [],
            group_secret=_SECRET,
            source_kind=DatasetSourceKind.SYNTHETIC,
        )
    with pytest.raises(ValueError, match="records_jsonl"):
        load_classification_dataset(" ", {})
    with pytest.raises(ValueError, match="invalid"):
        load_classification_dataset("[]\n", {})
