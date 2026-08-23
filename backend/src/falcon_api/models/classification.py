"""Persist bounded transaction-classification results and provenance."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)
from falcon_api.infrastructure.persistence import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import enum_sql_values


class TransactionClassification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store one immutable-current classification result per transaction."""

    __tablename__ = "transaction_classifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transaction_classifications_user_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "transaction_id"],
            ["transactions.user_id", "transactions.id"],
            name="fk_transaction_classifications_owner_transaction",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["assigned_category_id", "subcategory_code"],
            ["categories.id", "categories.classification_code"],
            name="fk_transaction_classifications_taxonomy_category",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "transaction_id",
            name="uq_transaction_classifications_owner_transaction",
        ),
        UniqueConstraint(
            "user_id",
            "transaction_id",
            "id",
            name="uq_transaction_classifications_owner_transaction_id",
        ),
        CheckConstraint(
            f"decision IN ({enum_sql_values(ClassificationDecision)})",
            name="decision_allowed",
        ),
        CheckConstraint(
            f"source IN ({enum_sql_values(ClassificationSource)})",
            name="source_allowed",
        ),
        CheckConstraint(
            (
                "category_code IS NULL OR category_code IN "
                f"({enum_sql_values(ClassificationCategoryCode)})"
            ),
            name="category_code_allowed",
        ),
        CheckConstraint(
            (
                "subcategory_code IS NULL OR subcategory_code IN "
                f"({enum_sql_values(ClassificationSubcategoryCode)})"
            ),
            name="subcategory_code_allowed",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_bounded",
        ),
        CheckConstraint(
            "cardinality(reason_codes) BETWEEN 1 AND 5",
            name="reason_codes_bounded",
        ),
        CheckConstraint(
            (
                "reason_codes <@ ARRAY["
                f"{enum_sql_values(ClassificationReasonCode)}"
                "]::varchar[]"
            ),
            name="reason_codes_allowed",
        ),
        CheckConstraint(
            (
                "(decision = 'automatic' AND category_code IS NOT NULL "
                "AND subcategory_code IS NOT NULL "
                "AND assigned_category_id IS NOT NULL) OR "
                "(decision = 'suggested' AND category_code IS NOT NULL "
                "AND subcategory_code IS NOT NULL "
                "AND assigned_category_id IS NULL) OR "
                "(decision = 'abstained' AND category_code IS NULL "
                "AND subcategory_code IS NULL "
                "AND assigned_category_id IS NULL)"
            ),
            name="decision_target_consistent",
        ),
        CheckConstraint(
            (
                "((source IN ('rule', 'hybrid')) = "
                "(ruleset_version IS NOT NULL)) AND "
                "((source IN ('ml', 'hybrid')) = "
                "(model_version IS NOT NULL))"
            ),
            name="source_version_consistent",
        ),
        CheckConstraint(
            "length(trim(taxonomy_version)) > 0",
            name="taxonomy_version_not_blank",
        ),
        CheckConstraint(
            ("ruleset_version IS NULL OR length(trim(ruleset_version)) > 0"),
            name="ruleset_version_not_blank",
        ),
        CheckConstraint(
            ("model_version IS NULL OR length(trim(model_version)) > 0"),
            name="model_version_not_blank",
        ),
        Index(
            "ix_transaction_classifications_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_transaction_classifications_user_decision",
            "user_id",
            "decision",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(nullable=False)
    assigned_category_id: Mapped[UUID | None] = mapped_column(nullable=True)
    decision: Mapped[ClassificationDecision] = mapped_column(String(16), nullable=False)
    source: Mapped[ClassificationSource] = mapped_column(String(24), nullable=False)
    category_code: Mapped[ClassificationCategoryCode | None] = mapped_column(
        String(64), nullable=True
    )
    subcategory_code: Mapped[ClassificationSubcategoryCode | None] = mapped_column(
        String(64), nullable=True
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4, asdecimal=True), nullable=False
    )
    reason_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(64), dimensions=1), nullable=False
    )
    taxonomy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ruleset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)


class UserMerchantMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store one exact reviewed taxonomy mapping in a user's namespace."""

    __tablename__ = "user_merchant_memories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_merchant_memories_user_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["category_id", "subcategory_code"],
            ["categories.id", "categories.classification_code"],
            name="fk_user_merchant_memories_taxonomy_category",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_user_merchant_memories_user_id_id",
        ),
        UniqueConstraint(
            "user_id",
            "normalized_merchant",
            name="uq_user_merchant_memories_owner_merchant",
        ),
        CheckConstraint(
            "normalized_merchant = lower(normalized_merchant)",
            name="normalized_merchant_lowercase",
        ),
        CheckConstraint(
            "length(trim(normalized_merchant)) BETWEEN 1 AND 200",
            name="normalized_merchant_bounded",
        ),
        CheckConstraint(
            (f"category_code IN ({enum_sql_values(ClassificationCategoryCode)})"),
            name="category_code_allowed",
        ),
        CheckConstraint(
            (f"subcategory_code IN ({enum_sql_values(ClassificationSubcategoryCode)})"),
            name="subcategory_code_allowed",
        ),
        CheckConstraint(
            "length(trim(taxonomy_version)) > 0",
            name="taxonomy_version_not_blank",
        ),
        Index(
            "ix_user_merchant_memories_user_updated",
            "user_id",
            "updated_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    normalized_merchant: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[UUID] = mapped_column(nullable=False)
    category_code: Mapped[ClassificationCategoryCode] = mapped_column(
        String(64), nullable=False
    )
    subcategory_code: Mapped[ClassificationSubcategoryCode] = mapped_column(
        String(64), nullable=False
    )
    taxonomy_version: Mapped[str] = mapped_column(String(64), nullable=False)


class TransactionCategoryCorrection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append one trusted snapshot of a user's reviewed category decision."""

    __tablename__ = "transaction_category_corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transaction_category_corrections_user_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "transaction_id"],
            ["transactions.user_id", "transactions.id"],
            name="fk_transaction_category_corrections_owner_transaction",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "transaction_id", "classification_id"],
            [
                "transaction_classifications.user_id",
                "transaction_classifications.transaction_id",
                "transaction_classifications.id",
            ],
            name="fk_transaction_category_corrections_original_classification",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["selected_category_id"],
            ["categories.id"],
            name="fk_transaction_category_corrections_selected_category",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"original_decision IN ({enum_sql_values(ClassificationDecision)})",
            name="original_decision_allowed",
        ),
        CheckConstraint(
            f"original_source IN ({enum_sql_values(ClassificationSource)})",
            name="original_source_allowed",
        ),
        CheckConstraint(
            (
                "original_category_code IS NULL OR original_category_code IN "
                f"({enum_sql_values(ClassificationCategoryCode)})"
            ),
            name="original_category_code_allowed",
        ),
        CheckConstraint(
            (
                "original_subcategory_code IS NULL OR "
                "original_subcategory_code IN "
                f"({enum_sql_values(ClassificationSubcategoryCode)})"
            ),
            name="original_subcategory_code_allowed",
        ),
        CheckConstraint(
            "original_confidence >= 0 AND original_confidence <= 1",
            name="original_confidence_bounded",
        ),
        CheckConstraint(
            "cardinality(original_reason_codes) BETWEEN 1 AND 5",
            name="original_reason_codes_bounded",
        ),
        CheckConstraint(
            (
                "original_reason_codes <@ ARRAY["
                f"{enum_sql_values(ClassificationReasonCode)}"
                "]::varchar[]"
            ),
            name="original_reason_codes_allowed",
        ),
        CheckConstraint(
            (
                "(original_decision = 'abstained' AND "
                "original_category_code IS NULL AND "
                "original_subcategory_code IS NULL) OR "
                "(original_decision <> 'abstained' AND "
                "original_category_code IS NOT NULL AND "
                "original_subcategory_code IS NOT NULL)"
            ),
            name="original_target_consistent",
        ),
        CheckConstraint(
            (
                "((original_source IN ('rule', 'hybrid')) = "
                "(original_ruleset_version IS NOT NULL)) AND "
                "((original_source IN ('ml', 'hybrid')) = "
                "(original_model_version IS NOT NULL))"
            ),
            name="original_source_version_consistent",
        ),
        CheckConstraint(
            "length(trim(original_taxonomy_version)) > 0",
            name="original_taxonomy_version_not_blank",
        ),
        CheckConstraint(
            (
                "original_ruleset_version IS NULL OR "
                "length(trim(original_ruleset_version)) > 0"
            ),
            name="original_ruleset_version_not_blank",
        ),
        CheckConstraint(
            (
                "original_model_version IS NULL OR "
                "length(trim(original_model_version)) > 0"
            ),
            name="original_model_version_not_blank",
        ),
        CheckConstraint(
            (
                "selected_category_code IS NULL OR "
                "selected_category_code IN "
                f"({enum_sql_values(ClassificationSubcategoryCode)})"
            ),
            name="selected_category_code_allowed",
        ),
        Index(
            "ix_transaction_category_corrections_user_occurred",
            "user_id",
            "occurred_at",
        ),
        Index(
            "ix_transaction_category_corrections_transaction_occurred",
            "transaction_id",
            "occurred_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(nullable=False)
    classification_id: Mapped[UUID] = mapped_column(nullable=False)
    original_decision: Mapped[ClassificationDecision] = mapped_column(
        String(16), nullable=False
    )
    original_source: Mapped[ClassificationSource] = mapped_column(
        String(24), nullable=False
    )
    original_category_code: Mapped[ClassificationCategoryCode | None] = mapped_column(
        String(64), nullable=True
    )
    original_subcategory_code: Mapped[ClassificationSubcategoryCode | None] = (
        mapped_column(String(64), nullable=True)
    )
    original_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4, asdecimal=True), nullable=False
    )
    original_reason_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(64), dimensions=1), nullable=False
    )
    original_taxonomy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    original_ruleset_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    original_model_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    selected_category_id: Mapped[UUID] = mapped_column(nullable=False)
    selected_category_code: Mapped[ClassificationSubcategoryCode | None] = (
        mapped_column(String(64), nullable=True)
    )
    merchant_memory_id: Mapped[UUID | None] = mapped_column(nullable=True)
    occurred_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
