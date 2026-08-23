"""Tests for rules-first Phase 7.5 hybrid classification and abstention."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from falcon_api.classification.artifacts import (
    ClassifierArtifactUnavailableError,
)
from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.hybrid import (
    HybridClassificationService,
    MerchantMemoryMatch,
)
from falcon_api.classification.inference import (
    ClassifierMetadata,
    ConfidencePolicy,
    ModelCandidate,
    ModelPrediction,
)
from falcon_api.classification.rules import ClassificationRulesEngine, KeywordRule
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    subcategory_definition,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)
from falcon_api.models.enums import TransactionType

_MODEL_VERSION = "classification_test.1"


class FakeClassifier:
    def __init__(
        self,
        prediction: ModelPrediction,
        *,
        policy: ConfidencePolicy | None = None,
    ) -> None:
        self._prediction = prediction
        self._metadata = ClassifierMetadata(
            model_version=_MODEL_VERSION,
            feature_schema_version="2026.1",
            taxonomy_version="2026.1",
            classes=(
                ClassificationSubcategoryCode.RESTAURANTS,
                ClassificationSubcategoryCode.RENT,
                ClassificationSubcategoryCode.FUEL,
            ),
            confidence_policy=policy
            or ConfidencePolicy(
                automatic_confidence=Decimal("0.80"),
                suggestion_confidence=Decimal("0.50"),
                minimum_top_two_margin=Decimal("0.10"),
            ),
            production_eligible=prediction.production_eligible,
        )
        self.calls = 0

    @property
    def metadata(self) -> ClassifierMetadata:
        return self._metadata

    def predict(self, features):
        self.calls += 1
        return self._prediction


class FakeProvider:
    model_version = _MODEL_VERSION

    def __init__(self, classifier: FakeClassifier | None) -> None:
        self.classifier = classifier
        self.calls = 0

    def get_classifier(self) -> FakeClassifier:
        self.calls += 1
        if self.classifier is None:
            raise ClassifierArtifactUnavailableError("unavailable")
        return self.classifier


def _features(
    description: str = "local cafe evening meal",
    *,
    transaction_type: TransactionType = TransactionType.EXPENSE,
):
    amount = Decimal(500)
    if transaction_type is TransactionType.EXPENSE:
        amount = -amount
    return build_classification_features(
        TransactionFeatureInput(
            description=description,
            merchant_name=None,
            transaction_type=transaction_type,
            signed_amount=amount,
            transaction_date=date(2026, 8, 23),
            account_currency="INR",
        )
    )


def _prediction(
    subcategory: ClassificationSubcategoryCode = (
        ClassificationSubcategoryCode.RESTAURANTS
    ),
    *,
    confidence: str = "0.90",
    margin: str = "0.40",
    production_eligible: bool = True,
    model_version: str = _MODEL_VERSION,
) -> ModelPrediction:
    category, _ = subcategory_definition(subcategory)
    selected = ModelCandidate(
        category=category,
        subcategory=subcategory,
        probability=Decimal(confidence),
    )
    return ModelPrediction(
        selected=selected,
        alternatives=(selected,),
        confidence=Decimal(confidence),
        top_two_margin=Decimal(margin),
        model_version=model_version,
        production_eligible=production_eligible,
    )


def _service(
    prediction: ModelPrediction,
    *,
    rules_engine: ClassificationRulesEngine | None = None,
) -> tuple[HybridClassificationService, FakeProvider, FakeClassifier]:
    classifier = FakeClassifier(prediction)
    provider = FakeProvider(classifier)
    return (
        HybridClassificationService(
            classifier_provider=provider,
            rules_engine=rules_engine,
        ),
        provider,
        classifier,
    )


def test_high_precision_rule_returns_automatic_without_loading_model() -> None:
    provider = FakeProvider(None)
    service = HybridClassificationService(classifier_provider=provider)

    outcome = service.classify(_features("monthly apartment rent"))

    assert outcome.decision is ClassificationDecision.AUTOMATIC
    assert outcome.source is ClassificationSource.RULE
    assert outcome.subcategory is ClassificationSubcategoryCode.RENT
    assert outcome.reason_codes == (ClassificationReasonCode.KEYWORD_RULE,)
    assert outcome.ruleset_version == "2026.1"
    assert outcome.model_version is None
    assert provider.calls == 0


def test_exact_user_memory_runs_after_rules_and_before_model() -> None:
    provider = FakeProvider(None)
    service = HybridClassificationService(classifier_provider=provider)
    memory = MerchantMemoryMatch(
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.RESTAURANTS,
    )

    outcome = service.classify(_features(), merchant_memory=memory)

    assert outcome.decision is ClassificationDecision.AUTOMATIC
    assert outcome.source is ClassificationSource.MERCHANT_MEMORY
    assert outcome.confidence == Decimal("1.0000")
    assert outcome.reason_codes == (ClassificationReasonCode.USER_MERCHANT_MEMORY,)
    assert outcome.ruleset_version is None
    assert outcome.model_version is None
    assert provider.calls == 0


def test_global_rule_precedes_memory_and_incompatible_memory_is_ignored() -> None:
    provider = FakeProvider(None)
    service = HybridClassificationService(classifier_provider=provider)
    restaurant = MerchantMemoryMatch(
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.RESTAURANTS,
    )
    salary = MerchantMemoryMatch(
        category=ClassificationCategoryCode.INCOME,
        subcategory=ClassificationSubcategoryCode.SALARY,
    )

    ruled = service.classify(
        _features("monthly apartment rent"), merchant_memory=restaurant
    )
    incompatible = service.classify(_features(), merchant_memory=salary)

    assert ruled.source is ClassificationSource.RULE
    assert ruled.subcategory is ClassificationSubcategoryCode.RENT
    assert incompatible.decision is ClassificationDecision.ABSTAINED
    assert incompatible.reason_codes == (
        ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,
    )
    assert provider.calls == 1


def test_production_model_uses_automatic_and_suggestion_thresholds() -> None:
    automatic_service, _, _ = _service(_prediction(confidence="0.90"))
    suggested_service, _, _ = _service(_prediction(confidence="0.65"))

    automatic = automatic_service.classify(_features())
    suggested = suggested_service.classify(_features())

    assert automatic.decision is ClassificationDecision.AUTOMATIC
    assert suggested.decision is ClassificationDecision.SUGGESTED
    assert automatic.source is ClassificationSource.ML
    assert automatic.reason_codes == (ClassificationReasonCode.MODEL_PREDICTION,)
    assert automatic.model_version == _MODEL_VERSION


def test_low_confidence_and_small_margin_force_safe_abstention() -> None:
    low_service, _, _ = _service(_prediction(confidence="0.40"))
    ambiguous_service, _, _ = _service(_prediction(confidence="0.90", margin="0.05"))

    low = low_service.classify(_features())
    ambiguous = ambiguous_service.classify(_features())

    assert low.decision is ClassificationDecision.ABSTAINED
    assert low.reason_codes == (ClassificationReasonCode.LOW_CONFIDENCE,)
    assert ambiguous.decision is ClassificationDecision.ABSTAINED
    assert ambiguous.reason_codes == (ClassificationReasonCode.AMBIGUOUS_PREDICTION,)
    assert low.category is None and low.subcategory is None


def test_synthetic_provisional_model_can_suggest_but_never_auto_assign() -> None:
    service, _, _ = _service(_prediction(confidence="0.99", production_eligible=False))

    outcome = service.classify(_features())

    assert outcome.decision is ClassificationDecision.SUGGESTED
    assert outcome.reason_codes == (
        ClassificationReasonCode.MODEL_PREDICTION,
        ClassificationReasonCode.PROVISIONAL_MODEL,
    )


def test_direction_incompatible_prediction_abstains() -> None:
    service, _, _ = _service(_prediction(ClassificationSubcategoryCode.SALARY))

    outcome = service.classify(_features())

    assert outcome.decision is ClassificationDecision.ABSTAINED
    assert outcome.reason_codes == (
        ClassificationReasonCode.UNSUPPORTED_TRANSACTION_TYPE,
    )


def _conflict_engine() -> ClassificationRulesEngine:
    rules = (
        KeywordRule(
            "ambiguous_rent",
            ClassificationCategoryCode.HOUSING,
            ClassificationSubcategoryCode.RENT,
            frozenset({TransactionType.EXPENSE}),
            required_any=frozenset({"ambiguous"}),
            priority=500,
        ),
        KeywordRule(
            "ambiguous_fuel",
            ClassificationCategoryCode.TRANSPORTATION,
            ClassificationSubcategoryCode.FUEL,
            frozenset({TransactionType.EXPENSE}),
            required_any=frozenset({"ambiguous"}),
            priority=500,
        ),
    )
    return ClassificationRulesEngine(keyword_rules=rules)


def test_model_agreement_resolves_rule_conflict_with_hybrid_provenance() -> None:
    service, _, _ = _service(
        _prediction(ClassificationSubcategoryCode.RENT),
        rules_engine=_conflict_engine(),
    )

    outcome = service.classify(_features("ambiguous monthly payment"))

    assert outcome.decision is ClassificationDecision.AUTOMATIC
    assert outcome.source is ClassificationSource.HYBRID
    assert outcome.subcategory is ClassificationSubcategoryCode.RENT
    assert outcome.reason_codes == (
        ClassificationReasonCode.MODEL_PREDICTION,
        ClassificationReasonCode.RULE_MODEL_AGREEMENT,
    )
    assert outcome.ruleset_version == "2026.1"
    assert outcome.model_version == _MODEL_VERSION


def test_model_disagreement_cannot_override_rule_conflict() -> None:
    service, _, _ = _service(
        _prediction(ClassificationSubcategoryCode.RESTAURANTS),
        rules_engine=_conflict_engine(),
    )

    outcome = service.classify(_features("ambiguous monthly payment"))

    assert outcome.decision is ClassificationDecision.ABSTAINED
    assert outcome.source is ClassificationSource.HYBRID
    assert outcome.reason_codes == (ClassificationReasonCode.AMBIGUOUS_PREDICTION,)


def test_unavailable_or_wrong_identity_model_abstains_without_raw_error() -> None:
    unavailable = HybridClassificationService(
        classifier_provider=FakeProvider(None)
    ).classify(_features())
    wrong_service, _, _ = _service(_prediction(model_version="different.1"))
    wrong_identity = wrong_service.classify(_features())

    assert unavailable.reason_codes == (
        ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,
    )
    assert unavailable.confidence == Decimal(0)
    assert wrong_identity.reason_codes == (
        ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,
    )


def test_untrusted_prediction_eligibility_mismatch_abstains() -> None:
    service, _, classifier = _service(_prediction(production_eligible=False))
    classifier._metadata = replace(
        classifier.metadata,
        production_eligible=True,
    )

    outcome = service.classify(_features())

    assert outcome.decision is ClassificationDecision.ABSTAINED
    assert outcome.reason_codes == (ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,)


def test_unavailable_model_preserves_rule_conflict_provenance() -> None:
    service = HybridClassificationService(
        classifier_provider=FakeProvider(None),
        rules_engine=_conflict_engine(),
    )

    outcome = service.classify(_features("ambiguous payment"))

    assert outcome.source is ClassificationSource.HYBRID
    assert outcome.reason_codes == (
        ClassificationReasonCode.AMBIGUOUS_PREDICTION,
        ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,
    )
    assert outcome.ruleset_version == "2026.1"


def test_service_and_outcome_reject_invalid_contracts() -> None:
    with pytest.raises(TypeError, match="provider"):
        HybridClassificationService(
            classifier_provider=object()  # type: ignore[arg-type]
        )
    invalid_provider = FakeProvider(None)
    invalid_provider.model_version = ""
    with pytest.raises(ValueError, match="model version"):
        HybridClassificationService(classifier_provider=invalid_provider)
    service, _, _ = _service(_prediction())
    with pytest.raises(TypeError, match="features"):
        service.classify("unsafe")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="merchant_memory"):
        service.classify(_features(), merchant_memory=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MerchantMemoryMatch(
            category=ClassificationCategoryCode.SHOPPING,
            subcategory=ClassificationSubcategoryCode.RESTAURANTS,
        )

    valid = service.classify(_features())
    with pytest.raises(ValueError, match="confidence"):
        replace(valid, confidence=Decimal(2))
    with pytest.raises(ValueError, match="reason"):
        replace(valid, reason_codes=())
    with pytest.raises(ValueError, match="target"):
        replace(valid, category=None)
    with pytest.raises(ValueError, match="ruleset"):
        replace(valid, ruleset_version="unexpected")
