"""Add bounded owner-scoped assistant history and private audit metadata.

Revision ID: e8c2a6d1f704
Revises: d6f4b8a1c902
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8c2a6d1f704"
down_revision: str | Sequence[str] | None = "d6f4b8a1c902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_assistant_conversations_expiry_after_creation")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_assistant_conversations_user_id_users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_conversations")),
        sa.UniqueConstraint("id", "user_id", name="uq_assistant_conversations_id_owner"),
    )
    op.create_index("ix_assistant_conversations_owner_created", "assistant_conversations", ["user_id", "created_at"])
    op.create_index("ix_assistant_conversations_expiry", "assistant_conversations", ["expires_at"])

    op.create_table(
        "assistant_conversation_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_ciphertext", sa.Text(), nullable=False),
        sa.Column("answer_ciphertext", sa.Text(), nullable=False),
        sa.Column("packet_id", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 50", name=op.f("ck_assistant_conversation_turns_ordinal_bounded")),
        sa.CheckConstraint("char_length(question_ciphertext) BETWEEN 1 AND 16000", name=op.f("ck_assistant_conversation_turns_encrypted_question_bounded")),
        sa.CheckConstraint("char_length(answer_ciphertext) BETWEEN 1 AND 50000", name=op.f("ck_assistant_conversation_turns_encrypted_answer_bounded")),
        sa.CheckConstraint("packet_id ~ '^[0-9a-f]{64}$' OR packet_id IS NULL", name=op.f("ck_assistant_conversation_turns_packet_hash")),
        sa.ForeignKeyConstraint(["conversation_id", "user_id"], ["assistant_conversations.id", "assistant_conversations.user_id"], ondelete="CASCADE", name="fk_assistant_conversation_turns_conversation_owner"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_conversation_turns")),
        sa.UniqueConstraint("conversation_id", "ordinal", name="uq_assistant_turns_order"),
        sa.UniqueConstraint("id", "user_id", name="uq_assistant_turns_id_owner"),
    )
    op.create_index("ix_assistant_turns_owner_conversation", "assistant_conversation_turns", ["user_id", "conversation_id", "ordinal"])

    op.create_table(
        "assistant_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("packet_id", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('answered', 'limited', 'unavailable', 'refused')", name=op.f("ck_assistant_audit_events_event_type_allowed")),
        sa.CheckConstraint("latency_ms BETWEEN 0 AND 60000", name=op.f("ck_assistant_audit_events_latency_bounded")),
        sa.CheckConstraint("input_tokens BETWEEN 0 AND 32000", name=op.f("ck_assistant_audit_events_input_tokens_bounded")),
        sa.CheckConstraint("output_tokens BETWEEN 0 AND 4096", name=op.f("ck_assistant_audit_events_output_tokens_bounded")),
        sa.CheckConstraint("jsonb_typeof(evidence_ids) = 'array' AND jsonb_array_length(evidence_ids) <= 20", name=op.f("ck_assistant_audit_events_evidence_ids_bounded")),
        sa.ForeignKeyConstraint(["conversation_id", "user_id"], ["assistant_conversations.id", "assistant_conversations.user_id"], ondelete="CASCADE", name="fk_assistant_audit_events_conversation_owner"),
        sa.ForeignKeyConstraint(["turn_id", "user_id"], ["assistant_conversation_turns.id", "assistant_conversation_turns.user_id"], ondelete="CASCADE", name="fk_assistant_audit_events_turn_owner"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_audit_events")),
    )
    op.create_index("ix_assistant_audit_events_owner_created", "assistant_audit_events", ["user_id", "created_at"])

    # Append-only while retained; deletion is required for erasure and TTL expiry.
    op.execute("""
        CREATE FUNCTION reject_assistant_history_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'assistant history is append-only';
        END;
        $$
    """)
    for table in ("assistant_conversations", "assistant_conversation_turns", "assistant_audit_events"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_assistant_history_update()"
        )


def downgrade() -> None:
    for table in ("assistant_audit_events", "assistant_conversation_turns", "assistant_conversations"):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION reject_assistant_history_update()")
    op.drop_index("ix_assistant_audit_events_owner_created", table_name="assistant_audit_events")
    op.drop_table("assistant_audit_events")
    op.drop_index("ix_assistant_turns_owner_conversation", table_name="assistant_conversation_turns")
    op.drop_table("assistant_conversation_turns")
    op.drop_index("ix_assistant_conversations_expiry", table_name="assistant_conversations")
    op.drop_index("ix_assistant_conversations_owner_created", table_name="assistant_conversations")
    op.drop_table("assistant_conversations")
