"""Tests for strict Phase 7 classification schemas."""

from decimal import Decimal
from uuid import uuid4

import pytest
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.schemas.classification import (
    ClassificationBatchRequest,
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationResult,
    ClassificationSource,
    TransactionCategoryCorrectionRequest,
)
from pydantic import ValidationError


def test_batch_request_is_bounded_unique_and_frozen() -> None:
    identifiers = (uuid4(), uuid4())
    request = ClassificationBatchRequest(transaction_ids=identifiers)

    assert request.transaction_ids == identifiers
    with pytest.raises(ValidationError):
        ClassificationBatchRequest(
            transaction_ids=(identifiers[0], identifiers[0])
        )
    with pytest.raises(ValidationError):
        ClassificationBatchRequest(transaction_ids=())
    with pytest.raises(ValidationError):
        ClassificationBatchRequest(
            transaction_ids=tuple(uuid4() for _ in range(101))
        )
    with pytest.raises(ValidationError):
        ClassificationBatchRequest(transaction_ids=identifiers, user_id=uuid4())


def test_category_correction_accepts_only_the_reviewed_category() -> None:
    category_id = uuid4()

    request = TransactionCategoryCorrectionRequest(category_id=category_id)

    assert request.category_id == category_id
    with pytest.raises(ValidationError):
        TransactionCategoryCorrectionRequest(
            category_id=category_id,
            confidence="1",
        )


def test_rule_result_requires_consistent_target_and_provenance() -> None:
    result = ClassificationResult(
        transaction_id=uuid4(),
        decision=ClassificationDecision.AUTOMATIC,
        source=ClassificationSource.RULE,
        category_code=ClassificationCategoryCode.FOOD_DINING,
        subcategory_code=ClassificationSubcategoryCode.FOOD_DELIVERY,
        confidence=Decimal("1"),
        reason_codes=(ClassificationReasonCode.KNOWN_MERCHANT,),
        ruleset_version="2026.1",
    )

    assert result.taxonomy_version == "2026.1"
    assert result.model_version is None


def test_ml_abstention_exposes_no_forced_category() -> None:
    result = ClassificationResult(
        transaction_id=uuid4(),
        decision=ClassificationDecision.ABSTAINED,
        source=ClassificationSource.ML,
        category_code=None,
        subcategory_code=None,
        confidence=Decimal("0.41"),
        reason_codes=(ClassificationReasonCode.LOW_CONFIDENCE,),
        model_version="tfidf-logreg-2026.1",
    )

    assert result.category_code is None
    assert result.decision is ClassificationDecision.ABSTAINED


def test_abstention_cannot_hide_a_forced_category() -> None:
    with pytest.raises(ValidationError):
        ClassificationResult(
            transaction_id=uuid4(),
            decision=ClassificationDecision.ABSTAINED,
            source=ClassificationSource.ML,
            category_code=ClassificationCategoryCode.OTHER,
            subcategory_code=ClassificationSubcategoryCode.UNCATEGORIZED,
            confidence=Decimal("0.41"),
            reason_codes=(ClassificationReasonCode.LOW_CONFIDENCE,),
            model_version="tfidf-logreg-2026.1",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"subcategory_code": None},
        {"category_code": ClassificationCategoryCode.SHOPPING},
        {"ruleset_version": None},
        {"model_version": "unexpected-model"},
        {"reason_codes": (ClassificationReasonCode.KEYWORD_RULE,) * 2},
    ],
)
def test_inconsistent_classification_results_are_rejected(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "transaction_id": uuid4(),
        "decision": ClassificationDecision.SUGGESTED,
        "source": ClassificationSource.RULE,
        "category_code": ClassificationCategoryCode.FOOD_DINING,
        "subcategory_code": ClassificationSubcategoryCode.FOOD_DELIVERY,
        "confidence": Decimal("0.72"),
        "reason_codes": (ClassificationReasonCode.KEYWORD_RULE,),
        "ruleset_version": "2026.1",
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(values)


@pytest.mark.parametrize("confidence", [Decimal("-0.0001"), Decimal("1.0001")])
def test_confidence_is_a_bounded_exact_decimal(confidence: Decimal) -> None:
    with pytest.raises(ValidationError):
        ClassificationResult(
            transaction_id=uuid4(),
            decision=ClassificationDecision.ABSTAINED,
            source=ClassificationSource.ML,
            category_code=None,
            subcategory_code=None,
            confidence=confidence,
            reason_codes=(ClassificationReasonCode.LOW_CONFIDENCE,),
            model_version="model-1",
        )
