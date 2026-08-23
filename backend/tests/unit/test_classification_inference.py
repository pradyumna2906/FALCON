"""Tests for the dependency-light Phase 7.5 classifier adapter."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from falcon_api.classification.features import (
    ClassificationFeatures,
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.inference import (
    ClassifierMetadata,
    ConfidencePolicy,
    ModelCandidate,
    ModelPrediction,
    SklearnTransactionClassifier,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.models.enums import TransactionType


_CLASSES = (
    ClassificationSubcategoryCode.RESTAURANTS,
    ClassificationSubcategoryCode.GROCERIES,
    ClassificationSubcategoryCode.FUEL,
)


class FakeEstimator:
    """Pickle-safe probability estimator used only by contract tests."""

    def __init__(
        self,
        probabilities: object = ((0.7, 0.2, 0.1),),
        classes: tuple[object, ...] = tuple(item.value for item in _CLASSES),
    ) -> None:
        self.classes_ = classes
        self.probabilities = probabilities
        self.calls: list[list[str]] = []

    def predict_proba(self, values: list[str]) -> object:
        self.calls.append(values)
        return self.probabilities


def _policy() -> ConfidencePolicy:
    return ConfidencePolicy(
        automatic_confidence=Decimal("0.80"),
        suggestion_confidence=Decimal("0.50"),
        minimum_top_two_margin=Decimal("0.10"),
    )


def _metadata(*, production_eligible: bool = True) -> ClassifierMetadata:
    return ClassifierMetadata(
        model_version="classification_test.1",
        feature_schema_version="2026.1",
        taxonomy_version="2026.1",
        classes=_CLASSES,
        confidence_policy=_policy(),
        production_eligible=production_eligible,
    )


def _features() -> ClassificationFeatures:
    return build_classification_features(
        TransactionFeatureInput(
            description="UPI North Cafe evening meal",
            merchant_name="North Cafe",
            transaction_type=TransactionType.EXPENSE,
            signed_amount=Decimal("-650"),
            transaction_date=date(2026, 8, 23),
            account_currency="INR",
        )
    )


def test_classifier_returns_bounded_deterministic_top_two_prediction() -> None:
    estimator = FakeEstimator(((0.12344, 0.67656, 0.2),))
    classifier = SklearnTransactionClassifier(estimator, _metadata())

    prediction = classifier.predict(_features())

    assert prediction.selected.subcategory is ClassificationSubcategoryCode.GROCERIES
    assert prediction.selected.category is ClassificationCategoryCode.FOOD_DINING
    assert prediction.confidence == Decimal("0.6766")
    assert prediction.top_two_margin == Decimal("0.4766")
    assert [item.subcategory for item in prediction.alternatives] == [
        ClassificationSubcategoryCode.GROCERIES,
        ClassificationSubcategoryCode.FUEL,
    ]
    assert prediction.model_version == "classification_test.1"
    assert estimator.calls[0][0].endswith("weekend_1 recurring_0")


def test_equal_probabilities_resolve_by_manifest_class_order() -> None:
    classifier = SklearnTransactionClassifier(
        FakeEstimator(((0.4, 0.4, 0.2),)), _metadata()
    )

    prediction = classifier.predict(_features())

    assert prediction.selected.subcategory is ClassificationSubcategoryCode.RESTAURANTS
    assert prediction.top_two_margin == Decimal("0.0000")


@pytest.mark.parametrize(
    "values",
    [
        (Decimal("NaN"), Decimal("0.5"), Decimal("0.1")),
        (Decimal("1.1"), Decimal("0.5"), Decimal("0.1")),
        (Decimal("0.8"), Decimal("0.9"), Decimal("0.1")),
    ],
)
def test_confidence_policy_rejects_invalid_values(
    values: tuple[Decimal, Decimal, Decimal],
) -> None:
    with pytest.raises(ValueError):
        ConfidencePolicy(*values)


@pytest.mark.parametrize(
    "changes",
    [
        {"model_version": ""},
        {"feature_schema_version": "old"},
        {"taxonomy_version": "old"},
        {"classes": (_CLASSES[0],)},
        {"classes": (_CLASSES[0], _CLASSES[0])},
        {"production_eligible": 1},
    ],
)
def test_classifier_metadata_rejects_invalid_contract(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(_metadata(), **changes)


def test_classifier_rejects_missing_surface_and_class_mismatch() -> None:
    with pytest.raises(TypeError, match="probabilistic"):
        SklearnTransactionClassifier(object(), _metadata())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="classes"):
        SklearnTransactionClassifier(
            FakeEstimator(classes=("restaurants", "fuel")),
            _metadata(),
        )
    with pytest.raises(ValueError, match="taxonomy"):
        SklearnTransactionClassifier(
            FakeEstimator(classes=("restaurants", "not_a_label", "fuel")),
            _metadata(),
        )


@pytest.mark.parametrize(
    ("probabilities", "error"),
    [
        (None, ValueError),
        ((), ValueError),
        (((0.7, 0.2, 0.1), (0.7, 0.2, 0.1)), ValueError),
        (((0.7, 0.3),), ValueError),
        (((0.7, "bad", 0.3),), ValueError),
        (((0.7, -0.1, 0.4),), ValueError),
        (((float("nan"), 0.5, 0.5),), ValueError),
        (((0.7, 0.2, 0.2),), ValueError),
    ],
)
def test_classifier_rejects_invalid_estimator_probability_output(
    probabilities: object,
    error: type[Exception],
) -> None:
    classifier = SklearnTransactionClassifier(
        FakeEstimator(probabilities), _metadata()
    )

    with pytest.raises(error):
        classifier.predict(_features())


def test_classifier_rejects_invalid_or_incompatible_features() -> None:
    classifier = SklearnTransactionClassifier(FakeEstimator(), _metadata())
    with pytest.raises(TypeError):
        classifier.predict("unsafe")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="feature-schema"):
        classifier.predict(replace(_features(), schema_version="old"))


def test_model_candidate_and_prediction_invariants_are_enforced() -> None:
    selected = ModelCandidate(
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.RESTAURANTS,
        probability=Decimal("0.8"),
    )
    with pytest.raises(ValueError, match="taxonomy"):
        replace(selected, category=ClassificationCategoryCode.SHOPPING)
    with pytest.raises(ValueError, match="probability"):
        replace(selected, probability=Decimal("2"))

    prediction = ModelPrediction(
        selected=selected,
        alternatives=(selected,),
        confidence=Decimal("0.8"),
        top_two_margin=Decimal("0.8"),
        model_version="classification_test.1",
        production_eligible=True,
    )
    with pytest.raises(ValueError, match="lead"):
        replace(prediction, alternatives=())
    with pytest.raises(ValueError, match="confidence"):
        replace(prediction, confidence=Decimal("0.7"))
    with pytest.raises(ValueError, match="margin"):
        replace(prediction, top_two_margin=Decimal("2"))
