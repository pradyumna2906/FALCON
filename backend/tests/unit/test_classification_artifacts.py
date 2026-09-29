"""Tests for trusted Phase 7.5 artifact packaging, registry, and lazy loading."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import pickle
import platform
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from falcon_api.classification.artifacts import (
    MODEL_ARTIFACT_FILENAME,
    MODEL_ARTIFACT_MANIFEST_FILENAME,
    MODEL_ARTIFACT_MANIFEST_VERSION,
    ClassifierArtifactCompatibilityError,
    ClassifierArtifactIntegrityError,
    ClassifierArtifactUnavailableError,
    LazyClassifierProvider,
    LibraryVersion,
    ModelArtifactManifest,
    ModelArtifactRegistry,
    package_model_comparison_result,
)
from falcon_api.classification.dataset import DatasetSourceKind
from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.inference import ConfidencePolicy
from falcon_api.classification.taxonomy import ClassificationSubcategoryCode
from falcon_api.classification.training import compare_classification_models
from falcon_api.models.enums import TransactionType
from scripts.build_classification_evidence import build_reference_dataset


_VERSION = "classification_test.1"
_CLASSES = (
    ClassificationSubcategoryCode.RESTAURANTS,
    ClassificationSubcategoryCode.GROCERIES,
    ClassificationSubcategoryCode.FUEL,
)


class RegistryEstimator:
    """Pickle-safe estimator used to verify checksum-before-load behavior."""

    classes_ = tuple(item.value for item in _CLASSES)

    def predict_proba(self, values: list[str]) -> list[list[float]]:
        return [[0.8, 0.1, 0.1] for _ in values]


def _libraries() -> tuple[LibraryVersion, ...]:
    return tuple(
        LibraryVersion(name=name, version=version)
        for name, version in sorted(
            {
                "python": platform.python_version(),
                "numpy": importlib.metadata.version("numpy"),
                "scipy": importlib.metadata.version("scipy"),
                "scikit_learn": importlib.metadata.version("scikit-learn"),
                "joblib": importlib.metadata.version("joblib"),
            }.items()
        )
    )


def _manifest(payload: bytes, **changes: object) -> ModelArtifactManifest:
    values: dict[str, object] = {
        "manifest_version": MODEL_ARTIFACT_MANIFEST_VERSION,
        "model_version": _VERSION,
        "candidate": "tfidf_logistic_regression",
        "artifact_filename": MODEL_ARTIFACT_FILENAME,
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
        "artifact_size_bytes": len(payload),
        "dataset_version": "test.1",
        "dataset_sha256": "a" * 64,
        "dataset_source_kind": DatasetSourceKind.SYNTHETIC,
        "feature_schema_version": "2026.1",
        "taxonomy_version": "2026.1",
        "split_id": "split_test",
        "random_seed": 42,
        "classes": _CLASSES,
        "confidence_policy": ConfidencePolicy(
            automatic_confidence=Decimal("0.8"),
            suggestion_confidence=Decimal("0.5"),
            minimum_top_two_margin=Decimal("0.1"),
        ),
        "production_eligible": False,
        "library_versions": _libraries(),
    }
    values.update(changes)
    return ModelArtifactManifest(**values)  # type: ignore[arg-type]


def _write_registry(
    root: Path,
    *,
    payload: bytes | None = None,
    manifest: ModelArtifactManifest | None = None,
) -> tuple[ModelArtifactRegistry, ModelArtifactManifest]:
    payload = payload if payload is not None else pickle.dumps(RegistryEstimator())
    manifest = manifest or _manifest(payload)
    directory = root / manifest.model_version
    directory.mkdir(parents=True)
    (directory / MODEL_ARTIFACT_FILENAME).write_bytes(payload)
    (directory / MODEL_ARTIFACT_MANIFEST_FILENAME).write_text(
        manifest.to_json(), encoding="utf-8"
    )
    return ModelArtifactRegistry(root), manifest


def _features():
    return build_classification_features(
        TransactionFeatureInput(
            description="Local cafe meal",
            merchant_name="Local Cafe",
            transaction_type=TransactionType.EXPENSE,
            signed_amount=Decimal("-450"),
            transaction_date=date(2026, 8, 23),
            account_currency="INR",
        )
    )


def test_manifest_round_trip_is_strict_and_json_safe() -> None:
    payload = pickle.dumps(RegistryEstimator())
    manifest = _manifest(payload)

    restored = ModelArtifactManifest.from_dict(json.loads(manifest.to_json()))

    assert restored == manifest
    assert restored.to_metadata().model_version == _VERSION
    assert "artifact_filename" in restored.to_dict()


@pytest.mark.parametrize(
    "changes",
    [
        {"manifest_version": "old"},
        {"model_version": "bad version"},
        {"candidate": "transformer"},
        {"artifact_filename": "../model.pkl"},
        {"artifact_sha256": "bad"},
        {"artifact_size_bytes": 0},
        {"dataset_sha256": "bad"},
        {"feature_schema_version": "old"},
        {"taxonomy_version": "old"},
        {"split_id": "invalid"},
        {"random_seed": -1},
        {"classes": (_CLASSES[0],)},
        {"classes": (_CLASSES[0], _CLASSES[0])},
        {"production_eligible": 1},
        {"library_versions": _libraries()[:-1]},
    ],
)
def test_manifest_rejects_invalid_or_incomplete_metadata(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _manifest(pickle.dumps(RegistryEstimator()), **changes)


def test_production_manifest_requires_complete_taxonomy() -> None:
    with pytest.raises(ValueError, match="complete taxonomy"):
        _manifest(
            pickle.dumps(RegistryEstimator()),
            production_eligible=True,
        )


def test_manifest_loader_rejects_unknown_fields_and_invalid_nested_shape() -> None:
    value = _manifest(pickle.dumps(RegistryEstimator())).to_dict()
    value["unexpected"] = True
    with pytest.raises(ValueError, match="shape"):
        ModelArtifactManifest.from_dict(value)

    value.pop("unexpected")
    value["confidence_policy"] = {"automatic_confidence": "0.8"}
    with pytest.raises(ValueError, match="invalid"):
        ModelArtifactManifest.from_dict(value)


def test_registry_verifies_manifest_checksum_and_loads_classifier(
    tmp_path: Path,
) -> None:
    registry, manifest = _write_registry(tmp_path)

    restored = registry.load_manifest(_VERSION)
    classifier = registry.load_classifier(_VERSION)
    prediction = classifier.predict(_features())

    assert restored == manifest
    assert prediction.model_version == _VERSION
    assert prediction.selected.subcategory is ClassificationSubcategoryCode.RESTAURANTS


def test_lazy_provider_caches_one_verified_classifier_across_threads(
    tmp_path: Path,
) -> None:
    registry, _ = _write_registry(tmp_path)
    provider = LazyClassifierProvider(registry, model_version=_VERSION)

    assert provider.is_loaded is False
    with ThreadPoolExecutor(max_workers=8) as executor:
        loaded = list(executor.map(lambda _: provider.get_classifier(), range(16)))

    assert provider.is_loaded is True
    assert len({id(classifier) for classifier in loaded}) == 1


def test_lazy_provider_retries_after_artifact_becomes_available(tmp_path: Path) -> None:
    registry = ModelArtifactRegistry(tmp_path)
    provider = LazyClassifierProvider(registry, model_version=_VERSION)
    with pytest.raises(ClassifierArtifactUnavailableError):
        provider.get_classifier()

    _write_registry(tmp_path)
    assert provider.get_classifier().metadata.model_version == _VERSION


def test_registry_rejects_missing_corrupted_or_invalid_artifacts(
    tmp_path: Path,
) -> None:
    registry = ModelArtifactRegistry(tmp_path)
    with pytest.raises(ClassifierArtifactUnavailableError):
        registry.load_manifest(_VERSION)
    with pytest.raises(ClassifierArtifactUnavailableError):
        registry.load_manifest("../escape")

    payload = pickle.dumps(RegistryEstimator())
    registry, manifest = _write_registry(tmp_path, payload=payload)
    artifact = tmp_path / _VERSION / MODEL_ARTIFACT_FILENAME
    artifact.write_bytes(payload + b"corrupt")
    with pytest.raises(ClassifierArtifactIntegrityError, match="size"):
        registry.load_classifier(_VERSION)

    artifact.write_bytes(b"x" * len(payload))
    with pytest.raises(ClassifierArtifactIntegrityError, match="checksum"):
        registry.load_classifier(_VERSION)

    invalid_payload = b"x" * len(payload)
    invalid_manifest = replace(
        manifest,
        artifact_sha256=hashlib.sha256(invalid_payload).hexdigest(),
    )
    (tmp_path / _VERSION / MODEL_ARTIFACT_MANIFEST_FILENAME).write_text(
        invalid_manifest.to_json(), encoding="utf-8"
    )
    with pytest.raises(ClassifierArtifactIntegrityError, match="deserialization"):
        registry.load_classifier(_VERSION)


def test_registry_rejects_manifest_identity_and_library_incompatibility(
    tmp_path: Path,
) -> None:
    payload = pickle.dumps(RegistryEstimator())
    wrong_identity = _manifest(payload, model_version="classification_other.1")
    directory = tmp_path / _VERSION
    directory.mkdir()
    (directory / MODEL_ARTIFACT_MANIFEST_FILENAME).write_text(
        wrong_identity.to_json(), encoding="utf-8"
    )
    registry = ModelArtifactRegistry(tmp_path)
    with pytest.raises(ClassifierArtifactIntegrityError, match="identity"):
        registry.load_manifest(_VERSION)

    libraries = tuple(
        replace(item, version="0.0") if item.name == "scikit_learn" else item
        for item in _libraries()
    )
    compatible_identity = _manifest(payload, library_versions=libraries)
    (directory / MODEL_ARTIFACT_MANIFEST_FILENAME).write_text(
        compatible_identity.to_json(), encoding="utf-8"
    )
    (directory / MODEL_ARTIFACT_FILENAME).write_bytes(payload)
    with pytest.raises(ClassifierArtifactCompatibilityError):
        registry.load_classifier(_VERSION)


def test_end_to_end_packaging_matches_evidence_and_loads_lazily(
    tmp_path: Path,
) -> None:
    result = compare_classification_models(build_reference_dataset())
    manifest = package_model_comparison_result(
        result,
        registry_root=tmp_path,
        model_version="classification_2026_1_demo.1",
    )
    provider = LazyClassifierProvider(
        ModelArtifactRegistry(tmp_path),
        model_version=manifest.model_version,
    )

    prediction = provider.get_classifier().predict(_features())

    assert manifest.production_eligible is False
    assert manifest.artifact_sha256 == next(
        item.artifact_sha256
        for item in result.report.evaluations
        if item.candidate is result.report.selected_candidate
    )
    assert prediction.production_eligible is False
    with pytest.raises(FileExistsError):
        package_model_comparison_result(
            result,
            registry_root=tmp_path,
            model_version=manifest.model_version,
        )


def test_packaging_rejects_estimator_that_no_longer_matches_evidence(
    tmp_path: Path,
) -> None:
    result = compare_classification_models(build_reference_dataset())
    selected = result.report.selected_candidate
    evaluations = tuple(
        replace(item, artifact_sha256="0" * 64)
        if item.candidate is selected
        else item
        for item in result.report.evaluations
    )
    corrupted = replace(result, report=replace(result.report, evaluations=evaluations))

    with pytest.raises(ClassifierArtifactIntegrityError, match="evidence"):
        package_model_comparison_result(
            corrupted,
            registry_root=tmp_path,
            model_version="classification_corrupt.1",
        )
