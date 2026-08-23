"""Privacy-bounded, versioned datasets for transaction classification."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping

from falcon_api.classification.features import (
    CLASSIFICATION_FEATURE_SCHEMA_VERSION,
    MAX_DESCRIPTION_TOKENS,
    MAX_MERCHANT_TOKENS,
    AmountBand,
    ClassificationFeatures,
    PaymentChannel,
)
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    validate_classification_target,
)
from falcon_api.models.enums import TransactionType


CLASSIFICATION_DATASET_VERSION = "2026.1"
MINIMUM_GROUP_SECRET_BYTES = 32
_DATASET_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_PRIVATE_IDENTIFIER = re.compile(r"^(?:rec|grp)_[a-f0-9]{32}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class DatasetSourceKind(StrEnum):
    """Reviewed source classes without exposing source-system identity."""

    SYNTHETIC = "synthetic"
    REVIEWED_DEIDENTIFIED = "reviewed_deidentified"


@dataclass(frozen=True, slots=True)
class LabeledFeatureSample:
    """One private builder input; source and group keys are never exported."""

    source_key: str
    group_key: str
    features: ClassificationFeatures
    category: ClassificationCategoryCode
    subcategory: ClassificationSubcategoryCode
    merchant_group: bool

    def __post_init__(self) -> None:
        _validate_private_key(self.source_key, field_name="source_key")
        _validate_private_key(self.group_key, field_name="group_key")
        if not isinstance(self.features, ClassificationFeatures):
            raise TypeError("features must use the shared classification schema.")
        if self.features.schema_version != CLASSIFICATION_FEATURE_SCHEMA_VERSION:
            raise ValueError("The feature-schema version is not supported.")
        if type(self.merchant_group) is not bool:
            raise TypeError("merchant_group must be a boolean.")
        validate_classification_target(
            category=self.category,
            subcategory=self.subcategory,
            transaction_type=self.features.transaction_type,
        )


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    """One sanitized record safe for an approved private training export."""

    record_id: str
    group_id: str
    normalized_description: str
    description_tokens: tuple[str, ...]
    normalized_merchant: str | None
    payment_channel: PaymentChannel
    transaction_type: TransactionType
    account_currency: str
    amount_band: AmountBand
    month: int
    day_of_month: int
    weekday: int
    is_weekend: bool
    is_recurring_candidate: bool
    category: ClassificationCategoryCode
    subcategory: ClassificationSubcategoryCode
    merchant_group: bool
    feature_schema_version: str = CLASSIFICATION_FEATURE_SCHEMA_VERSION
    taxonomy_version: str = CLASSIFICATION_TAXONOMY_VERSION

    def __post_init__(self) -> None:
        if _PRIVATE_IDENTIFIER.fullmatch(self.record_id) is None:
            raise ValueError("record_id must be an opaque record identifier.")
        if not self.record_id.startswith("rec_"):
            raise ValueError("record_id must use the record namespace.")
        if _PRIVATE_IDENTIFIER.fullmatch(self.group_id) is None:
            raise ValueError("group_id must be an opaque group identifier.")
        if not self.group_id.startswith("grp_"):
            raise ValueError("group_id must use the group namespace.")
        if self.feature_schema_version != CLASSIFICATION_FEATURE_SCHEMA_VERSION:
            raise ValueError("The record feature-schema version is not supported.")
        if self.taxonomy_version != CLASSIFICATION_TAXONOMY_VERSION:
            raise ValueError("The record taxonomy version is not supported.")
        if not isinstance(self.normalized_description, str):
            raise TypeError("normalized_description must be text.")
        if (
            not isinstance(self.description_tokens, tuple)
            or not all(
                isinstance(token, str) and token
                for token in self.description_tokens
            )
            or len(self.description_tokens) > MAX_DESCRIPTION_TOKENS
            or self.normalized_description != " ".join(self.description_tokens)
        ):
            raise ValueError("description_tokens must match the bounded description.")
        if self.normalized_merchant is not None and (
            not isinstance(self.normalized_merchant, str)
            or not self.normalized_merchant
            or len(self.normalized_merchant.split()) > MAX_MERCHANT_TOKENS
        ):
            raise ValueError("normalized_merchant must be bounded normalized text.")
        if not isinstance(self.payment_channel, PaymentChannel):
            raise TypeError("payment_channel must be a reviewed enum value.")
        if not isinstance(self.transaction_type, TransactionType):
            raise TypeError("transaction_type must be a reviewed enum value.")
        if not isinstance(self.amount_band, AmountBand):
            raise TypeError("amount_band must be a reviewed enum value.")
        if not isinstance(self.account_currency, str) or _CURRENCY.fullmatch(
            self.account_currency
        ) is None:
            raise ValueError("account_currency must be an uppercase ISO-style code.")
        if type(self.month) is not int or not 1 <= self.month <= 12:
            raise ValueError("month must be in the calendar range.")
        if type(self.day_of_month) is not int or not 1 <= self.day_of_month <= 31:
            raise ValueError("day_of_month must be in the calendar range.")
        if type(self.weekday) is not int or not 0 <= self.weekday <= 6:
            raise ValueError("weekday must be in the calendar range.")
        if type(self.is_weekend) is not bool or self.is_weekend != (self.weekday >= 5):
            raise ValueError("is_weekend must agree with weekday.")
        if type(self.is_recurring_candidate) is not bool:
            raise TypeError("is_recurring_candidate must be a boolean.")
        if type(self.merchant_group) is not bool:
            raise TypeError("merchant_group must be a boolean.")
        validate_classification_target(
            category=self.category,
            subcategory=self.subcategory,
            transaction_type=self.transaction_type,
        )
        self.to_features()

    @property
    def target(self) -> str:
        """Return the stable leaf label learned by first-release models."""
        return self.subcategory.value

    def to_features(self) -> ClassificationFeatures:
        """Reconstruct the shared inference feature object without raw input."""
        return ClassificationFeatures(
            schema_version=self.feature_schema_version,
            normalized_description=self.normalized_description,
            description_tokens=self.description_tokens,
            normalized_merchant=self.normalized_merchant,
            payment_channel=self.payment_channel,
            transaction_type=self.transaction_type,
            account_currency=self.account_currency,
            amount_band=self.amount_band,
            month=self.month,
            day_of_month=self.day_of_month,
            weekday=self.weekday,
            is_weekend=self.is_weekend,
            is_recurring_candidate=self.is_recurring_candidate,
        )

    def model_text(self) -> str:
        """Return deterministic TF-IDF text plus bounded structured tokens."""
        fields = [self.normalized_description]
        if self.normalized_merchant:
            fields.append(self.normalized_merchant)
        fields.extend(
            (
                f"type_{self.transaction_type.value}",
                f"channel_{self.payment_channel.value}",
                f"amount_{self.amount_band.value}",
                f"currency_{self.account_currency.casefold()}",
                f"month_{self.month}",
                f"weekday_{self.weekday}",
                f"weekend_{int(self.is_weekend)}",
                f"recurring_{int(self.is_recurring_candidate)}",
            )
        )
        return " ".join(fields)

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""
        return {
            "record_id": self.record_id,
            "group_id": self.group_id,
            "feature_schema_version": self.feature_schema_version,
            "taxonomy_version": self.taxonomy_version,
            "normalized_description": self.normalized_description,
            "description_tokens": list(self.description_tokens),
            "normalized_merchant": self.normalized_merchant,
            "payment_channel": self.payment_channel.value,
            "transaction_type": self.transaction_type.value,
            "account_currency": self.account_currency,
            "amount_band": self.amount_band.value,
            "month": self.month,
            "day_of_month": self.day_of_month,
            "weekday": self.weekday,
            "is_weekend": self.is_weekend,
            "is_recurring_candidate": self.is_recurring_candidate,
            "category": self.category.value,
            "subcategory": self.subcategory.value,
            "merchant_group": self.merchant_group,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DatasetRecord:
        """Validate and restore one serialized dataset record."""
        expected = {
            "record_id",
            "group_id",
            "feature_schema_version",
            "taxonomy_version",
            "normalized_description",
            "description_tokens",
            "normalized_merchant",
            "payment_channel",
            "transaction_type",
            "account_currency",
            "amount_band",
            "month",
            "day_of_month",
            "weekday",
            "is_weekend",
            "is_recurring_candidate",
            "category",
            "subcategory",
            "merchant_group",
        }
        if set(value) != expected:
            raise ValueError("The dataset record shape is not supported.")
        tokens = value["description_tokens"]
        if not isinstance(tokens, list) or not all(
            isinstance(token, str) for token in tokens
        ):
            raise ValueError("description_tokens must be a JSON string array.")
        return cls(
            record_id=value["record_id"],
            group_id=value["group_id"],
            feature_schema_version=value["feature_schema_version"],
            taxonomy_version=value["taxonomy_version"],
            normalized_description=value["normalized_description"],
            description_tokens=tuple(tokens),
            normalized_merchant=value["normalized_merchant"],
            payment_channel=PaymentChannel(value["payment_channel"]),
            transaction_type=TransactionType(value["transaction_type"]),
            account_currency=value["account_currency"],
            amount_band=AmountBand(value["amount_band"]),
            month=value["month"],
            day_of_month=value["day_of_month"],
            weekday=value["weekday"],
            is_weekend=value["is_weekend"],
            is_recurring_candidate=value["is_recurring_candidate"],
            category=ClassificationCategoryCode(value["category"]),
            subcategory=ClassificationSubcategoryCode(value["subcategory"]),
            merchant_group=value["merchant_group"],
        )


@dataclass(frozen=True, slots=True)
class DatasetLabelCount:
    """One immutable leaf-label count used in a manifest."""

    label: str
    count: int


@dataclass(frozen=True, slots=True)
class ClassificationDatasetManifest:
    """Reproducibility and integrity metadata without financial text."""

    dataset_version: str
    source_kind: DatasetSourceKind
    feature_schema_version: str
    taxonomy_version: str
    record_count: int
    group_count: int
    merchant_group_count: int
    label_counts: tuple[DatasetLabelCount, ...]
    records_sha256: str

    def to_dict(self) -> dict[str, object]:
        """Return stable publishable manifest data."""
        return {
            "dataset_version": self.dataset_version,
            "source_kind": self.source_kind.value,
            "feature_schema_version": self.feature_schema_version,
            "taxonomy_version": self.taxonomy_version,
            "record_count": self.record_count,
            "group_count": self.group_count,
            "merchant_group_count": self.merchant_group_count,
            "label_counts": [
                {"label": item.label, "count": item.count}
                for item in self.label_counts
            ],
            "records_sha256": self.records_sha256,
        }


@dataclass(frozen=True, slots=True)
class ClassificationDataset:
    """Immutable records plus a verified manifest."""

    records: tuple[DatasetRecord, ...]
    manifest: ClassificationDatasetManifest

    def __post_init__(self) -> None:
        expected = _build_manifest(
            self.records,
            dataset_version=self.manifest.dataset_version,
            source_kind=self.manifest.source_kind,
        )
        if expected != self.manifest:
            raise ValueError("Dataset records do not match their manifest.")

    def records_jsonl(self) -> str:
        """Serialize records deterministically for approved encrypted storage."""
        return "".join(
            f"{_canonical_json(record.to_dict())}\n" for record in self.records
        )


def build_classification_dataset(
    samples: Iterable[LabeledFeatureSample],
    *,
    group_secret: bytes,
    source_kind: DatasetSourceKind,
    dataset_version: str = CLASSIFICATION_DATASET_VERSION,
) -> ClassificationDataset:
    """Pseudonymize private keys and build a leakage-auditable dataset."""
    if (
        not isinstance(group_secret, bytes)
        or len(group_secret) < MINIMUM_GROUP_SECRET_BYTES
    ):
        raise ValueError("group_secret must contain at least 32 private bytes.")
    if _DATASET_IDENTIFIER.fullmatch(dataset_version) is None:
        raise ValueError("dataset_version must be a stable identifier.")
    if not isinstance(source_kind, DatasetSourceKind):
        raise TypeError("source_kind must be a reviewed dataset source.")

    records: list[DatasetRecord] = []
    source_ids: set[str] = set()
    feature_fingerprints: set[str] = set()
    group_targets: dict[
        str,
        tuple[ClassificationCategoryCode, ClassificationSubcategoryCode],
    ] = {}
    for sample in samples:
        if not isinstance(sample, LabeledFeatureSample):
            raise TypeError("samples must contain labeled feature samples.")
        record_id = _opaque_id("rec", sample.source_key, group_secret)
        group_id = _opaque_id("grp", sample.group_key, group_secret)
        if record_id in source_ids:
            raise ValueError("Duplicate source records are forbidden.")
        source_ids.add(record_id)
        fingerprint = _feature_fingerprint(sample)
        if fingerprint in feature_fingerprints:
            raise ValueError("Duplicate labeled feature records are forbidden.")
        feature_fingerprints.add(fingerprint)
        target = (sample.category, sample.subcategory)
        existing_target = group_targets.setdefault(group_id, target)
        if existing_target != target:
            raise ValueError("A dataset group cannot contain multiple labels.")
        features = sample.features
        records.append(
            DatasetRecord(
                record_id=record_id,
                group_id=group_id,
                normalized_description=features.normalized_description,
                description_tokens=features.description_tokens,
                normalized_merchant=features.normalized_merchant,
                payment_channel=features.payment_channel,
                transaction_type=features.transaction_type,
                account_currency=features.account_currency,
                amount_band=features.amount_band,
                month=features.month,
                day_of_month=features.day_of_month,
                weekday=features.weekday,
                is_weekend=features.is_weekend,
                is_recurring_candidate=features.is_recurring_candidate,
                category=sample.category,
                subcategory=sample.subcategory,
                merchant_group=sample.merchant_group,
            )
        )
    if not records:
        raise ValueError("A classification dataset cannot be empty.")
    ordered = tuple(sorted(records, key=lambda record: record.record_id))
    manifest = _build_manifest(
        ordered,
        dataset_version=dataset_version,
        source_kind=source_kind,
    )
    return ClassificationDataset(records=ordered, manifest=manifest)


def load_classification_dataset(
    records_jsonl: str,
    manifest_data: Mapping[str, Any],
) -> ClassificationDataset:
    """Load an exact dataset and reject shape or checksum corruption."""
    if not isinstance(records_jsonl, str) or not records_jsonl.strip():
        raise ValueError("records_jsonl must contain dataset records.")
    records: list[DatasetRecord] = []
    try:
        for line in records_jsonl.splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Each dataset line must be a JSON object.")
            records.append(DatasetRecord.from_dict(value))
        label_counts = tuple(
            DatasetLabelCount(label=item["label"], count=item["count"])
            for item in manifest_data["label_counts"]
        )
        manifest = ClassificationDatasetManifest(
            dataset_version=manifest_data["dataset_version"],
            source_kind=DatasetSourceKind(manifest_data["source_kind"]),
            feature_schema_version=manifest_data["feature_schema_version"],
            taxonomy_version=manifest_data["taxonomy_version"],
            record_count=manifest_data["record_count"],
            group_count=manifest_data["group_count"],
            merchant_group_count=manifest_data["merchant_group_count"],
            label_counts=label_counts,
            records_sha256=manifest_data["records_sha256"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("The classification dataset is invalid.") from exc
    return ClassificationDataset(records=tuple(records), manifest=manifest)


def _build_manifest(
    records: tuple[DatasetRecord, ...],
    *,
    dataset_version: str,
    source_kind: DatasetSourceKind,
) -> ClassificationDatasetManifest:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.target] = counts.get(record.target, 0) + 1
    payload = "".join(
        f"{_canonical_json(record.to_dict())}\n" for record in records
    ).encode("utf-8")
    return ClassificationDatasetManifest(
        dataset_version=dataset_version,
        source_kind=source_kind,
        feature_schema_version=CLASSIFICATION_FEATURE_SCHEMA_VERSION,
        taxonomy_version=CLASSIFICATION_TAXONOMY_VERSION,
        record_count=len(records),
        group_count=len({record.group_id for record in records}),
        merchant_group_count=sum(record.merchant_group for record in records),
        label_counts=tuple(
            DatasetLabelCount(label=label, count=count)
            for label, count in sorted(counts.items())
        ),
        records_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _opaque_id(namespace: str, private_key: str, secret: bytes) -> str:
    digest = hmac.new(
        secret,
        f"falcon-classification:{namespace}:{private_key}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{namespace}_{digest}"


def _feature_fingerprint(sample: LabeledFeatureSample) -> str:
    features = sample.features
    value = {
        "description": features.normalized_description,
        "merchant": features.normalized_merchant,
        "channel": features.payment_channel.value,
        "type": features.transaction_type.value,
        "currency": features.account_currency,
        "amount_band": features.amount_band.value,
        "month": features.month,
        "day": features.day_of_month,
        "weekday": features.weekday,
        "weekend": features.is_weekend,
        "recurring": features.is_recurring_candidate,
        "category": sample.category.value,
        "subcategory": sample.subcategory.value,
    }
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_private_key(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be text.")
    if not value.strip() or len(value) > 256:
        raise ValueError(f"{field_name} must be bounded and non-blank.")
