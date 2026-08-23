"""Stable contracts for transaction classification."""

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
    "CATEGORY_DEFINITIONS",
    "CLASSIFICATION_TAXONOMY_VERSION",
    "CategoryDefinition",
    "ClassificationCategoryCode",
    "ClassificationSubcategoryCode",
    "SubcategoryDefinition",
    "category_definition",
    "subcategory_definition",
    "validate_classification_target",
]
