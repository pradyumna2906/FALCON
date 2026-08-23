"""Persist bounded transaction-classification results and provenance."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

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
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import enum_sql_values
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
            (
                "ruleset_version IS NULL OR "
                "length(trim(ruleset_version)) > 0"
            ),
            name="ruleset_version_not_blank",
        ),
        CheckConstraint(
            (
                "model_version IS NULL OR "
                "length(trim(model_version)) > 0"
            ),
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
    decision: Mapped[ClassificationDecision] = mapped_column(
        String(16), nullable=False
    )
    source: Mapped[ClassificationSource] = mapped_column(
        String(24), nullable=False
    )
    category_code: Mapped[ClassificationCategoryCode | None] = mapped_column(
        String(64), nullable=True
    )
    subcategory_code: Mapped[
        ClassificationSubcategoryCode | None
    ] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4, asdecimal=True), nullable=False
    )
    reason_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(64), dimensions=1), nullable=False
    )
    taxonomy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ruleset_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    model_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
