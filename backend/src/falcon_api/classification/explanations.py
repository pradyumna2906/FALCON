"""Stable, privacy-bounded explanations for classification reason codes."""

from types import MappingProxyType
from typing import Final

from falcon_api.classification.types import ClassificationReasonCode


_EXPLANATION_MESSAGES: Final = MappingProxyType(
    {
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
)

if frozenset(_EXPLANATION_MESSAGES) != frozenset(ClassificationReasonCode):
    raise RuntimeError("Every classification reason code requires one explanation.")


def explanation_message(reason_code: ClassificationReasonCode) -> str:
    """Return one static message without interpolating transaction data."""
    return _EXPLANATION_MESSAGES[reason_code]
