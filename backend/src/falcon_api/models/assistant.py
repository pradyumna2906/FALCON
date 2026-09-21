"""Curated public knowledge used by the grounded assistant."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from falcon_api.infrastructure.persistence import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)


class AssistantKnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable curated source version with explicit retirement state."""

    __tablename__ = "assistant_knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "slug",
            "version",
            name="uq_assistant_knowledge_documents_slug_version",
        ),
        CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="slug_format",
        ),
        CheckConstraint(
            "length(trim(title)) > 0 AND length(trim(version)) > 0",
            name="identity_not_blank",
        ),
        CheckConstraint(
            "source_uri ~ '^https://'",
            name="source_uri_https",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_hash_sha256_hex",
        ),
        CheckConstraint(
            "jsonb_typeof(topics) = 'array' AND jsonb_array_length(topics) > 0",
            name="topics_non_empty_array",
        ),
        CheckConstraint(
            "topics <@ '[\"budgeting\", \"cash_flow\", \"savings\", "
            "\"emergency_funds\", \"debt\", \"forecasting\", "
            "\"goal_planning\", \"scenario_planning\", \"financial_risk\", "
            "\"financial_literacy\"]'::jsonb",
            name="topics_allowed",
        ),
        CheckConstraint(
            "retired_at IS NULL OR retired_at >= published_at",
            name="retirement_chronological",
        ),
        Index(
            "ix_assistant_knowledge_documents_active_published",
            "retired_at",
            "published_at",
        ),
    )

    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
    retired_at: Mapped[UTCDateTime | None] = mapped_column(nullable=True)

    chunks: Mapped[list[AssistantKnowledgeChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AssistantKnowledgeChunk.ordinal",
    )


class AssistantKnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bounded searchable excerpt from an approved public document."""

    __tablename__ = "assistant_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_assistant_knowledge_chunks_document_ordinal",
        ),
        UniqueConstraint(
            "document_id",
            "content_sha256",
            name="uq_assistant_knowledge_chunks_document_hash",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint(
            "length(trim(heading)) > 0 AND length(trim(content)) > 0",
            name="content_not_blank",
        ),
        CheckConstraint(
            "character_count = char_length(content) AND character_count > 0",
            name="character_count_matches",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_hash_sha256_hex",
        ),
        Index(
            "ix_assistant_knowledge_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_assistant_knowledge_chunks_document_ordinal",
            "document_id",
            "ordinal",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "assistant_knowledge_documents.id",
            name="fk_assistant_knowledge_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String(4_000), nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(heading, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(content, '')), 'B')",
            persisted=True,
        ),
        nullable=False,
    )

    document: Mapped[AssistantKnowledgeDocument] = relationship(
        back_populates="chunks"
    )


__all__ = ["AssistantKnowledgeChunk", "AssistantKnowledgeDocument"]
