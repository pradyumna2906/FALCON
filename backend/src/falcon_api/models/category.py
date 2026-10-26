"""System and user-owned transaction category model."""

from __future__ import annotations

from uuid import UUID

from falcon_api.infrastructure.persistence import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import CategoryKind, enum_sql_values
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Classify transactions in a system or private namespace."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(
            (
                "(is_system AND user_id IS NULL) OR "
                "(NOT is_system AND user_id IS NOT NULL)"
            ),
            name="system_owner_consistent",
        ),
        CheckConstraint(
            f"kind IN ({enum_sql_values(CategoryKind)})",
            name="kind_allowed",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="name_not_blank",
        ),
        CheckConstraint(
            "normalized_name = lower(normalized_name)",
            name="normalized_name_lowercase",
        ),
        CheckConstraint(
            "length(trim(normalized_name)) > 0",
            name="normalized_name_not_blank",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="display_order_non_negative",
        ),
        CheckConstraint(
            "classification_code IS NULL OR is_system",
            name="classification_code_system_only",
        ),
        CheckConstraint(
            (
                "classification_code IS NULL OR "
                "classification_code ~ '^[a-z][a-z0-9_]{0,63}$'"
            ),
            name="classification_code_format",
        ),
        UniqueConstraint(
            "id",
            "classification_code",
            name="uq_categories_id_classification_code",
        ),
        Index(
            "uq_categories_system_name",
            "normalized_name",
            unique=True,
            postgresql_where=text("is_system"),
        ),
        Index(
            "uq_categories_user_name",
            "user_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("NOT is_system"),
        ),
        Index(
            "ix_categories_user_active",
            "user_id",
            postgresql_where=text(
                "NOT is_system AND archived_at IS NULL"
            ),
        ),
        Index(
            "uq_categories_classification_code",
            "classification_code",
            unique=True,
            postgresql_where=text("classification_code IS NOT NULL"),
        ),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_categories_user_id_users",
        ),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    normalized_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    classification_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    kind: Mapped[CategoryKind] = mapped_column(
        String(16),
        nullable=False,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "categories.id",
            ondelete="RESTRICT",
            name="fk_categories_parent_id_categories",
        ),
        nullable=True,
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    archived_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )

    parent: Mapped[Category | None] = relationship(
        back_populates="children",
        remote_side="Category.id",
    )
    children: Mapped[list[Category]] = relationship(
        back_populates="parent",
    )
