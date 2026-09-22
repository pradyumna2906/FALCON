"""Add private message idempotency hashes to assistant history.

Revision ID: f2a7c9e4d816
Revises: e8c2a6d1f704
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a7c9e4d816"
down_revision: str | Sequence[str] | None = "e8c2a6d1f704"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_conversation_turns",
        sa.Column(
            "idempotency_key_hash",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        op.f(
            "ck_assistant_conversation_turns_"
            "idempotency_key_hash"
        ),
        "assistant_conversation_turns",
        "idempotency_key_hash ~ '^[0-9a-f]{64}$' "
        "OR idempotency_key_hash IS NULL",
    )
    op.create_unique_constraint(
        "uq_assistant_turns_conversation_idempotency",
        "assistant_conversation_turns",
        ["conversation_id", "idempotency_key_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_assistant_turns_conversation_idempotency",
        "assistant_conversation_turns",
        type_="unique",
    )
    op.drop_constraint(
        op.f(
            "ck_assistant_conversation_turns_"
            "idempotency_key_hash"
        ),
        "assistant_conversation_turns",
        type_="check",
    )
    op.drop_column(
        "assistant_conversation_turns",
        "idempotency_key_hash",
    )
