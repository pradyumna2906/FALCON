"""Dependency-light classifier interface and calibrated prediction contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol, Sequence

from falcon_api.classification.features import (
    CLASSIFICATION_FEATURE_SCHEMA_VERSION,
    ClassificationFeatures,
    classification_model_text,
)
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    subcategory_definition,
)


_CONFIDENCE_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class ConfidencePolicy:
    """Calibration-selected automatic, suggestion, and ambiguity thresholds."""

    automatic_confidence: Decimal
    suggestion_confidence: Decimal
    minimum_top_two_margin: Decimal

    def __post_init__(self) -> None:
        values = (
            self.automatic_confidence,
            self.suggestion_confidence,
            self.minimum_top_two_margin,
        )
        if any(
            not isinstance(value, Decimal)
            or not value.is_finite()
            or not Decimal("0") <= value <= Decimal("1")
            for value in values
        ):
            raise ValueError(
                "Confidence policy values must be exact decimals in [0, 1]."
            )
        if self.suggestion_confidence > self.automatic_confidence:
            raise ValueError(
                "Suggestion confidence cannot exceed automatic confidence."
            )


@dataclass(frozen=True, slots=True)
class ClassifierMetadata:
    """Trusted model identity and compatibility data used during inference."""

    model_version: str
    feature_schema_version: str
    taxonomy_version: str
    classes: tuple[ClassificationSubcategoryCode, ...]
    confidence_policy: ConfidencePolicy
    production_eligible: bool

    def __post_init__(self) -> None:
        if not self.model_version or len(self.model_version) > 64:
            raise ValueError("model_version must be bounded and non-blank.")
        if self.feature_schema_version != CLASSIFICATION_FEATURE_SCHEMA_VERSION:
            raise ValueError("The model feature-schema version is incompatible.")
        if self.taxonomy_version != CLASSIFICATION_TAXONOMY_VERSION:
            raise ValueError("The model taxonomy version is incompatible.")
        if (
            not isinstance(self.classes, tuple)
            or not all(
                isinstance(value, ClassificationSubcategoryCode)
                for value in self.classes
            )
            or len(self.classes) < 2
            or len(set(self.classes)) != len(self.classes)
        ):
            raise ValueError(
                "A classifier requires at least two unique taxonomy leaves."
            )
        if not isinstance(self.confidence_policy, ConfidencePolicy):
            raise TypeError(
                "confidence_policy must use the calibrated policy contract."
            )
        if type(self.production_eligible) is not bool:
            raise TypeError("production_eligible must be a boolean.")


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    """One bounded top prediction without raw features or estimator internals."""

    category: ClassificationCategoryCode
    subcategory: ClassificationSubcategoryCode
    probability: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.category, ClassificationCategoryCode) or not isinstance(
            self.subcategory, ClassificationSubcategoryCode
        ):
            raise TypeError("A model candidate requires taxonomy enum values.")
        parent, _ = subcategory_definition(self.subcategory)
        if parent is not self.category:
            raise ValueError("A model candidate has an invalid taxonomy target.")
        if (
            not isinstance(self.probability, Decimal)
            or not self.probability.is_finite()
            or not Decimal("0") <= self.probability <= Decimal("1")
        ):
            raise ValueError(
                "Candidate probability must be an exact decimal in [0, 1]."
            )


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    """Top-two calibrated model output consumed by hybrid orchestration."""

    selected: ModelCandidate
    alternatives: tuple[ModelCandidate, ...]
    confidence: Decimal
    top_two_margin: Decimal
    model_version: str
    production_eligible: bool

    def __post_init__(self) -> None:
        if not self.alternatives or self.alternatives[0] != self.selected:
            raise ValueError("The selected candidate must lead the alternatives.")
        if len(self.alternatives) > 2:
            raise ValueError("At most two model candidates may cross the boundary.")
        if len({candidate.subcategory for candidate in self.alternatives}) != len(
            self.alternatives
        ):
            raise ValueError("Model candidates must be unique.")
        if self.confidence != self.selected.probability:
            raise ValueError(
                "Prediction confidence must equal the selected probability."
            )
        if (
            not isinstance(self.top_two_margin, Decimal)
            or not self.top_two_margin.is_finite()
            or not Decimal("0") <= self.top_two_margin <= Decimal("1")
        ):
            raise ValueError("Top-two margin must be an exact decimal in [0, 1].")
        if not self.model_version or len(self.model_version) > 64:
            raise ValueError("model_version must be bounded and non-blank.")
        if type(self.production_eligible) is not bool:
            raise TypeError("production_eligible must be a boolean.")


class ProbabilisticEstimator(Protocol):
    """Minimal safe surface required from a loaded estimator."""

    classes_: Sequence[object]

    def predict_proba(self, values: Sequence[str]) -> object:
        """Return one probability row per model-text value."""


class TransactionClassifier(Protocol):
    """Stable interface used by orchestration instead of sklearn directly."""

    @property
    def metadata(self) -> ClassifierMetadata:
        """Return trusted compatibility and policy metadata."""

    def predict(self, features: ClassificationFeatures) -> ModelPrediction:
        """Predict one bounded top-two classification result."""


class SklearnTransactionClassifier:
    """Adapter around a reviewed estimator exposing only the stable interface."""

    def __init__(
        self,
        estimator: ProbabilisticEstimator,
        metadata: ClassifierMetadata,
    ) -> None:
        if not hasattr(estimator, "classes_") or not callable(
            getattr(estimator, "predict_proba", None)
        ):
            raise TypeError("The artifact does not implement probabilistic inference.")
        estimator_classes = _estimator_classes(estimator)
        if estimator_classes != metadata.classes:
            raise ValueError("Estimator classes do not match trusted model metadata.")
        self._estimator = estimator
        self._metadata = metadata

    @property
    def metadata(self) -> ClassifierMetadata:
        """Return trusted model metadata."""
        return self._metadata

    def predict(self, features: ClassificationFeatures) -> ModelPrediction:
        """Run one probability inference and return only two bounded candidates."""
        if not isinstance(features, ClassificationFeatures):
            raise TypeError("features must use the shared classification schema.")
        if features.schema_version != self.metadata.feature_schema_version:
            raise ValueError("The inference feature-schema version is incompatible.")
        output = self._estimator.predict_proba([classification_model_text(features)])
        try:
            rows = list(output)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(
                "The estimator returned an invalid probability matrix."
            ) from exc
        if len(rows) != 1:
            raise ValueError("Single-record inference must return exactly one row.")
        try:
            probabilities = tuple(float(value) for value in rows[0])
        except (TypeError, ValueError) as exc:
            raise ValueError("The estimator returned invalid probabilities.") from exc
        _validate_probability_row(probabilities, expected=len(self.metadata.classes))
        ordered_indices = tuple(
            sorted(
                range(len(probabilities)),
                key=lambda index: (-probabilities[index], index),
            )[:2]
        )
        alternatives = tuple(
            _candidate(
                self.metadata.classes[index],
                probabilities[index],
            )
            for index in ordered_indices
        )
        margin = _decimal_probability(
            probabilities[ordered_indices[0]] - probabilities[ordered_indices[1]]
        )
        return ModelPrediction(
            selected=alternatives[0],
            alternatives=alternatives,
            confidence=alternatives[0].probability,
            top_two_margin=margin,
            model_version=self.metadata.model_version,
            production_eligible=self.metadata.production_eligible,
        )


def _estimator_classes(
    estimator: ProbabilisticEstimator,
) -> tuple[ClassificationSubcategoryCode, ...]:
    try:
        return tuple(
            ClassificationSubcategoryCode(str(value)) for value in estimator.classes_
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Estimator classes are not supported taxonomy leaves."
        ) from exc


def _validate_probability_row(
    probabilities: tuple[float, ...],
    *,
    expected: int,
) -> None:
    if len(probabilities) != expected:
        raise ValueError("Probability count does not match classifier classes.")
    if any(
        not math.isfinite(value) or value < 0 or value > 1
        for value in probabilities
    ):
        raise ValueError("Estimator probabilities must be finite values in [0, 1].")
    if not math.isclose(sum(probabilities), 1.0, rel_tol=1e-7, abs_tol=1e-7):
        raise ValueError("Estimator probabilities must sum to one.")


def _candidate(
    subcategory: ClassificationSubcategoryCode,
    probability: float,
) -> ModelCandidate:
    category, _ = subcategory_definition(subcategory)
    return ModelCandidate(
        category=category,
        subcategory=subcategory,
        probability=_decimal_probability(probability),
    )


def _decimal_probability(value: float) -> Decimal:
    bounded = min(1.0, max(0.0, value))
    return Decimal(str(bounded)).quantize(
        _CONFIDENCE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
