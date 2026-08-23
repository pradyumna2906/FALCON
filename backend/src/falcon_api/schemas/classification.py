"""Strict public contracts for transaction classification."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    validate_classification_target,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


VersionIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    ),
]
ConfidenceScore = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4),
]


class ClassificationSchema(BaseModel):
    """Forbid undeclared fields and freeze validated classification data."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class ClassificationBatchRequest(ClassificationSchema):
    """Select a bounded set of transactions owned by the principal."""

    transaction_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_transaction_ids(self) -> "ClassificationBatchRequest":
        """Prevent ambiguous duplicate work inside one batch."""
        if len(set(self.transaction_ids)) != len(self.transaction_ids):
            raise ValueError("transaction_ids must be unique.")
        return self


class TransactionCategoryCorrectionRequest(ClassificationSchema):
    """Record one reviewed category selection without accepting provenance."""

    category_id: UUID


class ClassificationResult(ClassificationSchema):
    """Expose a bounded prediction without raw features or model internals."""

    transaction_id: UUID
    decision: ClassificationDecision
    source: ClassificationSource
    category_code: ClassificationCategoryCode | None
    subcategory_code: ClassificationSubcategoryCode | None
    confidence: ConfidenceScore
    reason_codes: tuple[ClassificationReasonCode, ...] = Field(
        min_length=1,
        max_length=5,
    )
    taxonomy_version: VersionIdentifier = CLASSIFICATION_TAXONOMY_VERSION
    ruleset_version: VersionIdentifier | None = None
    model_version: VersionIdentifier | None = None

    @model_validator(mode="after")
    def validate_result_consistency(self) -> "ClassificationResult":
        """Keep decisions, targets, and provenance internally consistent."""
        has_category = self.category_code is not None
        has_subcategory = self.subcategory_code is not None
        if self.decision == ClassificationDecision.ABSTAINED:
            if has_category or has_subcategory:
                raise ValueError("An abstained result cannot assign a category.")
        elif not (has_category and has_subcategory):
            raise ValueError("A classified result requires a category and subcategory.")
        else:
            validate_classification_target(
                category=self.category_code,
                subcategory=self.subcategory_code,
            )

        uses_rules = self.source in {
            ClassificationSource.RULE,
            ClassificationSource.HYBRID,
        }
        uses_model = self.source in {
            ClassificationSource.ML,
            ClassificationSource.HYBRID,
        }
        if uses_rules != (self.ruleset_version is not None):
            raise ValueError("Rule provenance requires exactly one ruleset version.")
        if uses_model != (self.model_version is not None):
            raise ValueError("ML provenance requires exactly one model version.")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique.")
        return self
