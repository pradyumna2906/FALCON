"""Add immutable curated assistant knowledge and full-text retrieval.

Revision ID: d6f4b8a1c902
Revises: c4d7a9e2f816
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d6f4b8a1c902"
down_revision: str | Sequence[str] | None = "c4d7a9e2f816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    """Install curated public documents and bounded searchable chunks."""
    op.create_table(
        "assistant_knowledge_documents",
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column("topics", postgresql.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name=op.f("ck_assistant_knowledge_documents_slug_format"),
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0 AND length(trim(version)) > 0",
            name=op.f("ck_assistant_knowledge_documents_identity_not_blank"),
        ),
        sa.CheckConstraint(
            "source_uri ~ '^https://'",
            name=op.f("ck_assistant_knowledge_documents_source_uri_https"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_assistant_knowledge_documents_content_hash_sha256_hex"
            ),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(topics) = 'array' AND jsonb_array_length(topics) > 0",
            name=op.f(
                "ck_assistant_knowledge_documents_topics_non_empty_array"
            ),
        ),
        sa.CheckConstraint(
            "topics <@ '[\"budgeting\", \"cash_flow\", \"savings\", "
            "\"emergency_funds\", \"debt\", \"forecasting\", "
            "\"goal_planning\", \"scenario_planning\", \"financial_risk\", "
            "\"financial_literacy\"]'::jsonb",
            name=op.f("ck_assistant_knowledge_documents_topics_allowed"),
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= published_at",
            name=op.f(
                "ck_assistant_knowledge_documents_retirement_chronological"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_assistant_knowledge_documents")
        ),
        sa.UniqueConstraint(
            "slug",
            "version",
            name="uq_assistant_knowledge_documents_slug_version",
        ),
    )
    op.create_index(
        "ix_assistant_knowledge_documents_active_published",
        "assistant_knowledge_documents",
        ["retired_at", "published_at"],
        unique=False,
    )

    op.create_table(
        "assistant_knowledge_chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('english', coalesce(heading, '')), 'A') || "
                "setweight(to_tsvector('english', coalesce(content, '')), 'B')",
                persisted=True,
            ),
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "ordinal > 0",
            name=op.f("ck_assistant_knowledge_chunks_ordinal_positive"),
        ),
        sa.CheckConstraint(
            "length(trim(heading)) > 0 AND length(trim(content)) > 0",
            name=op.f("ck_assistant_knowledge_chunks_content_not_blank"),
        ),
        sa.CheckConstraint(
            "character_count = char_length(content) AND character_count > 0",
            name=op.f(
                "ck_assistant_knowledge_chunks_character_count_matches"
            ),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f(
                "ck_assistant_knowledge_chunks_content_hash_sha256_hex"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["assistant_knowledge_documents.id"],
            name="fk_assistant_knowledge_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_knowledge_chunks")),
        sa.UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_assistant_knowledge_chunks_document_ordinal",
        ),
        sa.UniqueConstraint(
            "document_id",
            "content_sha256",
            name="uq_assistant_knowledge_chunks_document_hash",
        ),
    )
    op.create_index(
        "ix_assistant_knowledge_chunks_document_ordinal",
        "assistant_knowledge_chunks",
        ["document_id", "ordinal"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_knowledge_chunks_search_vector",
        "assistant_knowledge_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    op.execute(
        """
        CREATE FUNCTION validate_assistant_knowledge_document_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'assistant knowledge documents cannot be deleted';
            END IF;
            IF OLD.slug IS DISTINCT FROM NEW.slug
               OR OLD.version IS DISTINCT FROM NEW.version
               OR OLD.title IS DISTINCT FROM NEW.title
               OR OLD.source_uri IS DISTINCT FROM NEW.source_uri
               OR OLD.topics IS DISTINCT FROM NEW.topics
               OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
               OR OLD.policy_version IS DISTINCT FROM NEW.policy_version
               OR OLD.published_at IS DISTINCT FROM NEW.published_at
               OR OLD.created_at IS DISTINCT FROM NEW.created_at
               OR OLD.retired_at IS NOT NULL
               OR NEW.retired_at IS NULL
               OR NEW.retired_at < OLD.published_at
               OR NEW.updated_at IS DISTINCT FROM NEW.retired_at
               OR NEW.updated_at < OLD.updated_at THEN
                RAISE EXCEPTION 'assistant knowledge documents are immutable except retirement';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_assistant_knowledge_documents_controlled_update
        BEFORE UPDATE OR DELETE ON assistant_knowledge_documents
        FOR EACH ROW EXECUTE FUNCTION validate_assistant_knowledge_document_update()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_assistant_knowledge_chunk_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'assistant knowledge chunks are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_assistant_knowledge_chunks_immutable
        BEFORE UPDATE OR DELETE ON assistant_knowledge_chunks
        FOR EACH ROW EXECUTE FUNCTION reject_assistant_knowledge_chunk_mutation()
        """
    )


def downgrade() -> None:
    """Remove the curated assistant knowledge index."""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_assistant_knowledge_chunks_immutable "
        "ON assistant_knowledge_chunks"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_assistant_knowledge_chunk_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_assistant_knowledge_documents_controlled_update "
        "ON assistant_knowledge_documents"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS validate_assistant_knowledge_document_update()"
    )
    op.drop_index(
        "ix_assistant_knowledge_chunks_search_vector",
        table_name="assistant_knowledge_chunks",
    )
    op.drop_index(
        "ix_assistant_knowledge_chunks_document_ordinal",
        table_name="assistant_knowledge_chunks",
    )
    op.drop_table("assistant_knowledge_chunks")
    op.drop_index(
        "ix_assistant_knowledge_documents_active_published",
        table_name="assistant_knowledge_documents",
    )
    op.drop_table("assistant_knowledge_documents")
