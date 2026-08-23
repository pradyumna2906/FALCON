"""Trusted model packaging, integrity verification, registry, and lazy loading."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import pickle
import platform
import re
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from falcon_api.classification.dataset import DatasetSourceKind
from falcon_api.classification.features import CLASSIFICATION_FEATURE_SCHEMA_VERSION
from falcon_api.classification.inference import (
    ClassifierMetadata,
    ConfidencePolicy,
    SklearnTransactionClassifier,
    TransactionClassifier,
)
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationSubcategoryCode,
)

if TYPE_CHECKING:
    from falcon_api.classification.training import ModelComparisonResult


MODEL_ARTIFACT_MANIFEST_VERSION = "2026.1"
MODEL_ARTIFACT_FILENAME = "model.pkl"
MODEL_ARTIFACT_MANIFEST_FILENAME = "manifest.json"
MAX_MODEL_ARTIFACT_BYTES = 64 * 1024 * 1024
_VERSION = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_CHECKSUM = re.compile(r"^[a-f0-9]{64}$")
_LEARNED_CANDIDATES = frozenset(
    {"tfidf_logistic_regression", "tfidf_calibrated_linear_svm"}
)
_REQUIRED_LIBRARIES = frozenset(
    {"python", "numpy", "scipy", "scikit_learn", "joblib"}
)


class ClassifierArtifactError(RuntimeError):
    """Base error with a bounded message safe for domain translation."""


class ClassifierArtifactUnavailableError(ClassifierArtifactError):
    """The configured manifest or artifact is absent."""


class ClassifierArtifactIntegrityError(ClassifierArtifactError):
    """The artifact does not match reviewed integrity metadata."""


class ClassifierArtifactCompatibilityError(ClassifierArtifactError):
    """The artifact cannot run under the active contract or libraries."""


@dataclass(frozen=True, slots=True)
class LibraryVersion:
    """One exact training dependency version required for safe deserialization."""

    name: str
    version: str

    def __post_init__(self) -> None:
        if self.name not in _REQUIRED_LIBRARIES:
            raise ValueError("The artifact declares an unsupported library.")
        if not self.version or len(self.version) > 64:
            raise ValueError("Library versions must be bounded and non-blank.")


@dataclass(frozen=True, slots=True)
class ModelArtifactManifest:
    """Strict trusted metadata stored beside an excluded model binary."""

    manifest_version: str
    model_version: str
    candidate: str
    artifact_filename: str
    artifact_sha256: str
    artifact_size_bytes: int
    dataset_version: str
    dataset_sha256: str
    dataset_source_kind: DatasetSourceKind
    feature_schema_version: str
    taxonomy_version: str
    split_id: str
    random_seed: int
    classes: tuple[ClassificationSubcategoryCode, ...]
    confidence_policy: ConfidencePolicy
    production_eligible: bool
    library_versions: tuple[LibraryVersion, ...]

    def __post_init__(self) -> None:
        if self.manifest_version != MODEL_ARTIFACT_MANIFEST_VERSION:
            raise ValueError("The artifact-manifest version is not supported.")
        for name, value in (
            ("model_version", self.model_version),
            ("dataset_version", self.dataset_version),
        ):
            if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
                raise ValueError(f"{name} must be a stable identifier.")
        if self.candidate not in _LEARNED_CANDIDATES:
            raise ValueError("The artifact candidate is not approved.")
        if self.artifact_filename != MODEL_ARTIFACT_FILENAME:
            raise ValueError("The artifact filename is not approved.")
        if _CHECKSUM.fullmatch(self.artifact_sha256) is None:
            raise ValueError("The artifact checksum is invalid.")
        if not 0 < self.artifact_size_bytes <= MAX_MODEL_ARTIFACT_BYTES:
            raise ValueError("The artifact size is outside the approved bound.")
        if _CHECKSUM.fullmatch(self.dataset_sha256) is None:
            raise ValueError("The dataset checksum is invalid.")
        if not isinstance(self.dataset_source_kind, DatasetSourceKind):
            raise TypeError("dataset_source_kind must be a reviewed enum value.")
        if self.feature_schema_version != CLASSIFICATION_FEATURE_SCHEMA_VERSION:
            raise ValueError("The manifest feature-schema version is incompatible.")
        if self.taxonomy_version != CLASSIFICATION_TAXONOMY_VERSION:
            raise ValueError("The manifest taxonomy version is incompatible.")
        if not self.split_id.startswith("split_") or len(self.split_id) > 64:
            raise ValueError("split_id must be a stable split identifier.")
        if type(self.random_seed) is not int or self.random_seed < 0:
            raise ValueError("random_seed must be a non-negative integer.")
        if len(self.classes) < 2 or len(set(self.classes)) != len(self.classes):
            raise ValueError("Artifact classes must be unique taxonomy leaves.")
        all_classes = frozenset(ClassificationSubcategoryCode)
        if self.production_eligible and frozenset(self.classes) != all_classes:
            raise ValueError("A production artifact must cover the complete taxonomy.")
        if type(self.production_eligible) is not bool:
            raise TypeError("production_eligible must be a boolean.")
        declared_libraries = {item.name for item in self.library_versions}
        if declared_libraries != _REQUIRED_LIBRARIES:
            raise ValueError("The artifact must record every required library version.")
        if len(declared_libraries) != len(self.library_versions):
            raise ValueError("Artifact library declarations must be unique.")

    def to_metadata(self) -> ClassifierMetadata:
        """Return the dependency-free metadata consumed by the classifier."""
        return ClassifierMetadata(
            model_version=self.model_version,
            feature_schema_version=self.feature_schema_version,
            taxonomy_version=self.taxonomy_version,
            classes=self.classes,
            confidence_policy=self.confidence_policy,
            production_eligible=self.production_eligible,
        )

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-compatible trusted metadata."""
        return {
            "manifest_version": self.manifest_version,
            "model_version": self.model_version,
            "candidate": self.candidate,
            "artifact_filename": self.artifact_filename,
            "artifact_sha256": self.artifact_sha256,
            "artifact_size_bytes": self.artifact_size_bytes,
            "dataset_version": self.dataset_version,
            "dataset_sha256": self.dataset_sha256,
            "dataset_source_kind": self.dataset_source_kind.value,
            "feature_schema_version": self.feature_schema_version,
            "taxonomy_version": self.taxonomy_version,
            "split_id": self.split_id,
            "random_seed": self.random_seed,
            "classes": [value.value for value in self.classes],
            "confidence_policy": {
                "automatic_confidence": str(
                    self.confidence_policy.automatic_confidence
                ),
                "suggestion_confidence": str(
                    self.confidence_policy.suggestion_confidence
                ),
                "minimum_top_two_margin": str(
                    self.confidence_policy.minimum_top_two_margin
                ),
            },
            "production_eligible": self.production_eligible,
            "library_versions": {
                item.name: item.version
                for item in sorted(self.library_versions, key=lambda item: item.name)
            },
        }

    def to_json(self) -> str:
        """Serialize the strict manifest deterministically."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ModelArtifactManifest:
        """Reject unknown fields and restore trusted manifest data."""
        expected = {
            "manifest_version",
            "model_version",
            "candidate",
            "artifact_filename",
            "artifact_sha256",
            "artifact_size_bytes",
            "dataset_version",
            "dataset_sha256",
            "dataset_source_kind",
            "feature_schema_version",
            "taxonomy_version",
            "split_id",
            "random_seed",
            "classes",
            "confidence_policy",
            "production_eligible",
            "library_versions",
        }
        if set(value) != expected:
            raise ValueError("The artifact-manifest shape is not supported.")
        try:
            policy = value["confidence_policy"]
            libraries = value["library_versions"]
            if not isinstance(policy, dict) or set(policy) != {
                "automatic_confidence",
                "suggestion_confidence",
                "minimum_top_two_margin",
            }:
                raise ValueError("The confidence policy shape is invalid.")
            if not isinstance(libraries, dict):
                raise ValueError("Library versions must be a JSON object.")
            return cls(
                manifest_version=value["manifest_version"],
                model_version=value["model_version"],
                candidate=value["candidate"],
                artifact_filename=value["artifact_filename"],
                artifact_sha256=value["artifact_sha256"],
                artifact_size_bytes=value["artifact_size_bytes"],
                dataset_version=value["dataset_version"],
                dataset_sha256=value["dataset_sha256"],
                dataset_source_kind=DatasetSourceKind(
                    value["dataset_source_kind"]
                ),
                feature_schema_version=value["feature_schema_version"],
                taxonomy_version=value["taxonomy_version"],
                split_id=value["split_id"],
                random_seed=value["random_seed"],
                classes=tuple(
                    ClassificationSubcategoryCode(item)
                    for item in value["classes"]
                ),
                confidence_policy=ConfidencePolicy(
                    automatic_confidence=Decimal(
                        policy["automatic_confidence"]
                    ),
                    suggestion_confidence=Decimal(
                        policy["suggestion_confidence"]
                    ),
                    minimum_top_two_margin=Decimal(
                        policy["minimum_top_two_margin"]
                    ),
                ),
                production_eligible=value["production_eligible"],
                library_versions=tuple(
                    LibraryVersion(name=name, version=version)
                    for name, version in sorted(libraries.items())
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("The model artifact manifest is invalid.") from exc


class ModelArtifactRegistry:
    """Resolve only trusted version directories below one configured root."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise TypeError("Artifact registry root must be a Path.")
        self.root = root.resolve()

    def load_manifest(self, model_version: str) -> ModelArtifactManifest:
        """Load strict metadata without deserializing a model binary."""
        version_directory = self._version_directory(model_version)
        manifest_path = version_directory / MODEL_ARTIFACT_MANIFEST_FILENAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ClassifierArtifactUnavailableError(
                "The configured classifier manifest is unavailable."
            )
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("The artifact manifest must be a JSON object.")
            manifest = ModelArtifactManifest.from_dict(value)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ClassifierArtifactIntegrityError(
                "The configured classifier manifest failed validation."
            ) from exc
        if manifest.model_version != model_version:
            raise ClassifierArtifactIntegrityError(
                "The configured classifier manifest has the wrong identity."
            )
        return manifest

    def load_classifier(self, model_version: str) -> TransactionClassifier:
        """Verify compatibility and bytes before trusted pickle deserialization."""
        manifest = self.load_manifest(model_version)
        _verify_library_compatibility(manifest.library_versions)
        artifact_path = self._version_directory(model_version) / (
            manifest.artifact_filename
        )
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ClassifierArtifactUnavailableError(
                "The configured classifier artifact is unavailable."
            )
        try:
            stat = artifact_path.stat()
            if stat.st_size != manifest.artifact_size_bytes:
                raise ClassifierArtifactIntegrityError(
                    "The classifier artifact size does not match its manifest."
                )
            payload = artifact_path.read_bytes()
        except ClassifierArtifactIntegrityError:
            raise
        except OSError as exc:
            raise ClassifierArtifactUnavailableError(
                "The configured classifier artifact cannot be read."
            ) from exc
        if hashlib.sha256(payload).hexdigest() != manifest.artifact_sha256:
            raise ClassifierArtifactIntegrityError(
                "The classifier artifact checksum does not match its manifest."
            )
        try:
            estimator = pickle.loads(payload)
            return SklearnTransactionClassifier(estimator, manifest.to_metadata())
        except (ModuleNotFoundError, ImportError) as exc:
            raise ClassifierArtifactCompatibilityError(
                "The classifier runtime dependency is unavailable."
            ) from exc
        except Exception as exc:
            raise ClassifierArtifactIntegrityError(
                "The classifier artifact failed trusted deserialization."
            ) from exc

    def _version_directory(self, model_version: str) -> Path:
        if (
            not isinstance(model_version, str)
            or _VERSION.fullmatch(model_version) is None
        ):
            raise ClassifierArtifactUnavailableError(
                "The configured classifier version is invalid."
            )
        directory = (self.root / model_version).resolve()
        if directory.parent != self.root:
            raise ClassifierArtifactUnavailableError(
                "The configured classifier version is invalid."
            )
        return directory


class LazyClassifierProvider:
    """Thread-safe provider that loads and verifies a classifier only once."""

    def __init__(
        self,
        registry: ModelArtifactRegistry,
        *,
        model_version: str,
    ) -> None:
        if not isinstance(registry, ModelArtifactRegistry):
            raise TypeError("registry must be a model artifact registry.")
        if (
            not isinstance(model_version, str)
            or _VERSION.fullmatch(model_version) is None
        ):
            raise ValueError("model_version must be a stable identifier.")
        self._registry = registry
        self.model_version = model_version
        self._classifier: TransactionClassifier | None = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        """Return whether a verified estimator has been cached."""
        return self._classifier is not None

    def get_classifier(self) -> TransactionClassifier:
        """Load on first use, cache success, and permit retries after failures."""
        classifier = self._classifier
        if classifier is not None:
            return classifier
        with self._lock:
            classifier = self._classifier
            if classifier is None:
                classifier = self._registry.load_classifier(self.model_version)
                self._classifier = classifier
            return classifier


def package_model_comparison_result(
    result: ModelComparisonResult,
    *,
    registry_root: Path,
    model_version: str,
    overwrite: bool = False,
) -> ModelArtifactManifest:
    """Atomically package the selected in-memory model into an ignored registry."""
    if not isinstance(registry_root, Path):
        raise TypeError("registry_root must be a Path.")
    if not isinstance(model_version, str) or _VERSION.fullmatch(model_version) is None:
        raise ValueError("model_version must be a stable identifier.")
    if type(overwrite) is not bool:
        raise TypeError("overwrite must be a boolean.")
    report = result.report
    estimator = result.selected_estimator
    payload = pickle.dumps(estimator, protocol=5)
    artifact_checksum = hashlib.sha256(payload).hexdigest()
    selected_evidence = next(
        item
        for item in report.evaluations
        if item.candidate is report.selected_candidate
    )
    if (
        selected_evidence.artifact_sha256 != artifact_checksum
        or selected_evidence.artifact_size_bytes != len(payload)
    ):
        raise ClassifierArtifactIntegrityError(
            "The selected estimator does not match its evaluation evidence."
        )
    classes = tuple(
        ClassificationSubcategoryCode(str(value)) for value in estimator.classes_
    )
    thresholds = report.selected_thresholds
    manifest = ModelArtifactManifest(
        manifest_version=MODEL_ARTIFACT_MANIFEST_VERSION,
        model_version=model_version,
        candidate=report.selected_candidate.value,
        artifact_filename=MODEL_ARTIFACT_FILENAME,
        artifact_sha256=artifact_checksum,
        artifact_size_bytes=len(payload),
        dataset_version=report.dataset_version,
        dataset_sha256=report.dataset_sha256,
        dataset_source_kind=report.dataset_source_kind,
        feature_schema_version=report.feature_schema_version,
        taxonomy_version=report.taxonomy_version,
        split_id=report.split_id,
        random_seed=report.random_seed,
        classes=classes,
        confidence_policy=ConfidencePolicy(
            automatic_confidence=Decimal(str(thresholds.automatic_confidence)),
            suggestion_confidence=Decimal(str(thresholds.suggestion_confidence)),
            minimum_top_two_margin=Decimal(
                str(thresholds.minimum_top_two_margin)
            ),
        ),
        production_eligible=report.production_eligible,
        library_versions=tuple(
            LibraryVersion(name=name, version=version)
            for name, version in sorted(report.library_versions.items())
        ),
    )
    version_directory = registry_root.resolve() / model_version
    artifact_path = version_directory / MODEL_ARTIFACT_FILENAME
    manifest_path = version_directory / MODEL_ARTIFACT_MANIFEST_FILENAME
    if not overwrite and (artifact_path.exists() or manifest_path.exists()):
        raise FileExistsError("The model version already exists in the registry.")
    version_directory.mkdir(parents=True, exist_ok=True)
    _atomic_write(artifact_path, payload)
    _atomic_write(manifest_path, manifest.to_json().encode("utf-8"))
    return manifest


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _verify_library_compatibility(
    versions: tuple[LibraryVersion, ...],
) -> None:
    expected = {item.name: item.version for item in versions}
    active_python = platform.python_version()
    if _major_minor(active_python) != _major_minor(expected["python"]):
        raise ClassifierArtifactCompatibilityError(
            "The classifier Python version is incompatible."
        )
    distributions = {
        "numpy": "numpy",
        "scipy": "scipy",
        "scikit_learn": "scikit-learn",
        "joblib": "joblib",
    }
    for name, distribution in distributions.items():
        try:
            active = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ClassifierArtifactCompatibilityError(
                "A classifier runtime dependency is unavailable."
            ) from exc
        if active != expected[name]:
            raise ClassifierArtifactCompatibilityError(
                "A classifier runtime dependency version is incompatible."
            )


def _major_minor(version: str) -> tuple[int, int]:
    try:
        major, minor, *_ = version.split(".")
        return int(major), int(minor)
    except (TypeError, ValueError) as exc:
        raise ClassifierArtifactCompatibilityError(
            "The classifier Python version metadata is invalid."
        ) from exc
