"""Strict public contracts for transaction classification."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

from falcon_api.classification.explanations import explanation_message
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    validate_classification_target,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)

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
    Field(ge=Decimal(0), le=Decimal(1), max_digits=5, decimal_places=4),
]
MerchantName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ExplanationMessage = Annotated[
    str,
    StringConstraints(min_length=1, max_length=160),
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


class MerchantMemoryWriteRequest(ClassificationSchema):
    """Create or replace one exact personal merchant mapping."""

    merchant_name: MerchantName
    category_id: UUID


class MerchantMemoryListQuery(ClassificationSchema):
    """Select one bounded page of the principal's exact mappings."""

    cursor: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ] = None
    limit: int = Field(default=50, ge=1, le=100)


class ClassificationExplanation(ClassificationSchema):
    """Pair one stable reason code with a static human-readable message."""

    code: ClassificationReasonCode
    message: ExplanationMessage


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

    @field_validator("confidence")
    @classmethod
    def normalize_confidence_scale(cls, value: Decimal) -> Decimal:
        """Keep fresh and PostgreSQL-loaded responses byte-consistent."""
        return value.quantize(Decimal("0.0001"))

    @computed_field(return_type=tuple[ClassificationExplanation, ...])
    @property
    def explanations(self) -> tuple[ClassificationExplanation, ...]:
        """Derive safe explanations without accepting or storing client text."""
        return tuple(
            ClassificationExplanation(
                code=reason_code,
                message=explanation_message(reason_code),
            )
            for reason_code in self.reason_codes
        )

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


class ClassificationBatchResponse(ClassificationSchema):
    """Return results in the same order as the requested transaction IDs."""

    items: tuple[ClassificationResult, ...] = Field(min_length=1, max_length=100)


class MerchantMemoryResult(ClassificationSchema):
    """Expose one same-user mapping without returning its owner key."""

    id: UUID
    normalized_merchant: MerchantName
    category_id: UUID
    category_code: ClassificationCategoryCode
    subcategory_code: ClassificationSubcategoryCode
    taxonomy_version: VersionIdentifier = CLASSIFICATION_TAXONOMY_VERSION
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_memory_target(self) -> "MerchantMemoryResult":
        """Require the stored parent and leaf to remain taxonomy-compatible."""
        if self.taxonomy_version != CLASSIFICATION_TAXONOMY_VERSION:
            raise ValueError("Merchant memory uses an incompatible taxonomy version.")
        validate_classification_target(
            category=self.category_code,
            subcategory=self.subcategory_code,
        )
        return self


class MerchantMemoryPageResponse(ClassificationSchema):
    """Return a bounded lexicographic page of exact mappings."""

    items: tuple[MerchantMemoryResult, ...]
    next_cursor: MerchantName | None


class ClassificationCorrectionResult(ClassificationSchema):
    """Return the immutable correction identity and bounded source snapshot."""

    id: UUID
    transaction_id: UUID
    selected_category_id: UUID
    selected_category_code: ClassificationSubcategoryCode | None
    merchant_memory_id: UUID | None
    original: ClassificationResult
    occurred_at: datetime
