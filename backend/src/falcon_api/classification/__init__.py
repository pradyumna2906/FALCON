"""Stable contracts for transaction classification."""

from falcon_api.classification.features import (
    CLASSIFICATION_FEATURE_SCHEMA_VERSION,
    AmountBand,
    ClassificationFeatures,
    PaymentChannel,
    TransactionFeatureInput,
    amount_band,
    build_classification_features,
    detect_payment_channel,
    feature_record,
    normalize_merchant,
)
from falcon_api.classification.merchant_knowledge import (
    DEFAULT_MERCHANT_DEFINITIONS,
    DEFAULT_MERCHANT_KNOWLEDGE_BASE,
    MERCHANT_KNOWLEDGE_VERSION,
    MerchantDefinition,
    MerchantKnowledgeBase,
)
from falcon_api.classification.rules import (
    CLASSIFICATION_RULESET_VERSION,
    DEFAULT_KEYWORD_RULES,
    ClassificationRulesEngine,
    KeywordRule,
    RuleEvaluation,
    RuleMatch,
    RuleMatchKind,
)
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    CATEGORY_DEFINITIONS,
    CategoryDefinition,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    SubcategoryDefinition,
    category_definition,
    subcategory_definition,
    validate_classification_target,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)


__all__ = [
    "CLASSIFICATION_FEATURE_SCHEMA_VERSION",
    "CLASSIFICATION_RULESET_VERSION",
    "CATEGORY_DEFINITIONS",
    "CLASSIFICATION_TAXONOMY_VERSION",
    "AmountBand",
    "CategoryDefinition",
    "ClassificationFeatures",
    "ClassificationDecision",
    "ClassificationReasonCode",
    "ClassificationRulesEngine",
    "ClassificationSource",
    "ClassificationCategoryCode",
    "ClassificationSubcategoryCode",
    "PaymentChannel",
    "DEFAULT_KEYWORD_RULES",
    "DEFAULT_MERCHANT_DEFINITIONS",
    "DEFAULT_MERCHANT_KNOWLEDGE_BASE",
    "KeywordRule",
    "MERCHANT_KNOWLEDGE_VERSION",
    "MerchantDefinition",
    "MerchantKnowledgeBase",
    "RuleEvaluation",
    "RuleMatch",
    "RuleMatchKind",
    "SubcategoryDefinition",
    "TransactionFeatureInput",
    "amount_band",
    "build_classification_features",
    "category_definition",
    "detect_payment_channel",
    "feature_record",
    "normalize_merchant",
    "subcategory_definition",
    "validate_classification_target",
]
