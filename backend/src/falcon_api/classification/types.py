"""Shared bounded classification decision and explanation types."""

from enum import StrEnum


class ClassificationDecision(StrEnum):
    """Public action represented by one classifier result."""

    AUTOMATIC = "automatic"
    SUGGESTED = "suggested"
    ABSTAINED = "abstained"


class ClassificationSource(StrEnum):
    """Mechanism responsible for one classification result."""

    RULE = "rule"
    MERCHANT_MEMORY = "merchant_memory"
    ML = "ml"
    HYBRID = "hybrid"


class ClassificationReasonCode(StrEnum):
    """Bounded, non-sensitive explanations safe for clients and metrics."""

    KNOWN_MERCHANT = "known_merchant"
    KEYWORD_RULE = "keyword_rule"
    USER_MERCHANT_MEMORY = "user_merchant_memory"
    MODEL_PREDICTION = "model_prediction"
    RULE_MODEL_AGREEMENT = "rule_model_agreement"
    LOW_CONFIDENCE = "low_confidence"
    AMBIGUOUS_PREDICTION = "ambiguous_prediction"
    UNSUPPORTED_TRANSACTION_TYPE = "unsupported_transaction_type"
