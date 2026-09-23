"""Curated public knowledge used by the grounded assistant."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
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


class AssistantConversation(UUIDPrimaryKeyMixin, Base):
    """Owner-scoped container, removed with its turns on expiry or erasure."""

    __tablename__ = "assistant_conversations"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_assistant_conversations_id_owner"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_assistant_conversations_owner_created", "user_id", "created_at"),
        Index("ix_assistant_conversations_expiry", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_assistant_conversations_user_id_users"),
        nullable=False,
    )
    created_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
    expires_at: Mapped[UTCDateTime] = mapped_column(nullable=False)


class AssistantConversationTurn(UUIDPrimaryKeyMixin, Base):
    """Append-only user-visible exchange; never a raw provider response."""

    __tablename__ = "assistant_conversation_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["assistant_conversations.id", "assistant_conversations.user_id"],
            ondelete="CASCADE",
            name="fk_assistant_conversation_turns_conversation_owner",
        ),
        UniqueConstraint("conversation_id", "ordinal", name="uq_assistant_turns_order"),
        UniqueConstraint(
            "conversation_id",
            "idempotency_key_hash",
            name="uq_assistant_turns_conversation_idempotency",
        ),
        UniqueConstraint("id", "user_id", name="uq_assistant_turns_id_owner"),
        CheckConstraint("ordinal BETWEEN 1 AND 50", name="ordinal_bounded"),
        CheckConstraint("char_length(question_ciphertext) BETWEEN 1 AND 16000", name="encrypted_question_bounded"),
        CheckConstraint("char_length(answer_ciphertext) BETWEEN 1 AND 50000", name="encrypted_answer_bounded"),
        CheckConstraint("packet_id ~ '^[0-9a-f]{64}$' OR packet_id IS NULL", name="packet_hash"),
        CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$' "
            "OR idempotency_key_hash IS NULL",
            name="idempotency_key_hash",
        ),
        Index("ix_assistant_turns_owner_conversation", "user_id", "conversation_id", "ordinal"),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    question_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    answer_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    packet_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[UTCDateTime] = mapped_column(nullable=False)


class AssistantAuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only bounded provenance without questions, answers, or prompts."""

    __tablename__ = "assistant_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["assistant_conversations.id", "assistant_conversations.user_id"],
            ondelete="CASCADE",
            name="fk_assistant_audit_events_conversation_owner",
        ),
        ForeignKeyConstraint(
            ["turn_id", "user_id"],
            ["assistant_conversation_turns.id", "assistant_conversation_turns.user_id"],
            ondelete="CASCADE",
            name="fk_assistant_audit_events_turn_owner",
        ),
        CheckConstraint("event_type IN ('answered', 'limited', 'unavailable', 'refused')", name="event_type_allowed"),
        CheckConstraint("latency_ms BETWEEN 0 AND 60000", name="latency_bounded"),
        CheckConstraint("input_tokens BETWEEN 0 AND 32000", name="input_tokens_bounded"),
        CheckConstraint("output_tokens BETWEEN 0 AND 4096", name="output_tokens_bounded"),
        CheckConstraint("jsonb_typeof(evidence_ids) = 'array' AND jsonb_array_length(evidence_ids) <= 20", name="evidence_ids_bounded"),
        Index("ix_assistant_audit_events_owner_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    turn_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    packet_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[UTCDateTime] = mapped_column(nullable=False)


__all__ += ["AssistantAuditEvent", "AssistantConversation", "AssistantConversationTurn"]
