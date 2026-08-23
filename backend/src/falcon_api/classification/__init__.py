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


__all__ = [
    "CLASSIFICATION_FEATURE_SCHEMA_VERSION",
    "CATEGORY_DEFINITIONS",
    "CLASSIFICATION_TAXONOMY_VERSION",
    "AmountBand",
    "CategoryDefinition",
    "ClassificationFeatures",
    "ClassificationCategoryCode",
    "ClassificationSubcategoryCode",
    "PaymentChannel",
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
