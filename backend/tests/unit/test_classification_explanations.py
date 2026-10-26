"""Tests for bounded, deterministic classification explanations."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from falcon_api.classification.explanations import explanation_message
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)
from falcon_api.schemas.classification import ClassificationResult


_EXPECTED_MESSAGES = {
    ClassificationReasonCode.KNOWN_MERCHANT: (
        "Matched a reviewed merchant mapping."
    ),
    ClassificationReasonCode.KEYWORD_RULE: (
        "Matched a reviewed transaction rule."
    ),
    ClassificationReasonCode.USER_MERCHANT_MEMORY: (
        "Used your exact reviewed merchant preference."
    ),
    ClassificationReasonCode.MODEL_PREDICTION: (
        "Used the verified classification model."
    ),
    ClassificationReasonCode.RULE_MODEL_AGREEMENT: (
        "The model agreed with a leading rule candidate."
    ),
    ClassificationReasonCode.PROVISIONAL_MODEL: (
        "The model is provisional, so this result requires review."
    ),
    ClassificationReasonCode.CLASSIFIER_UNAVAILABLE: (
        "The classifier was unavailable, so no category was assigned."
    ),
    ClassificationReasonCode.LOW_CONFIDENCE: (
        "Confidence was too low to assign a category."
    ),
    ClassificationReasonCode.AMBIGUOUS_PREDICTION: (
        "The available evidence did not identify one clear category."
    ),
    ClassificationReasonCode.UNSUPPORTED_TRANSACTION_TYPE: (
        "The predicted category was incompatible with the transaction direction."
    ),
}


def _result() -> ClassificationResult:
    return ClassificationResult(
        transaction_id=uuid4(),
        decision=ClassificationDecision.SUGGESTED,
        source=ClassificationSource.HYBRID,
        category_code=ClassificationCategoryCode.FOOD_DINING,
        subcategory_code=ClassificationSubcategoryCode.RESTAURANTS,
        confidence=Decimal("0.7800"),
        reason_codes=(
            ClassificationReasonCode.KEYWORD_RULE,
            ClassificationReasonCode.RULE_MODEL_AGREEMENT,
        ),
        ruleset_version="2026.1",
        model_version="classification_test.1",
    )


def test_every_reason_code_has_one_stable_bounded_message() -> None:
    assert set(_EXPECTED_MESSAGES) == set(ClassificationReasonCode)
    for reason_code, expected in _EXPECTED_MESSAGES.items():
        message = explanation_message(reason_code)
        assert message == expected
        assert 1 <= len(message) <= 160
        assert "{" not in message
        assert "}" not in message


def test_result_serializes_explanations_in_reason_code_order() -> None:
    result = _result()

    assert result.model_dump(mode="json")["explanations"] == [
        {
            "code": "keyword_rule",
            "message": "Matched a reviewed transaction rule.",
        },
        {
            "code": "rule_model_agreement",
            "message": "The model agreed with a leading rule candidate.",
        },
    ]
    serialization_schema = ClassificationResult.model_json_schema(
        mode="serialization"
    )
    assert serialization_schema["properties"]["explanations"]["readOnly"] is True


def test_explanations_cannot_be_supplied_or_interpolated_by_clients() -> None:
    submitted = _result().model_dump(exclude={"explanations"})
    submitted["explanations"] = [
        {"code": "keyword_rule", "message": "SECRET MERCHANT"}
    ]

    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(submitted)
