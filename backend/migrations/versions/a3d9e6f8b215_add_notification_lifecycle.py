"""Add owner-scoped notification inbox and preferences.

Revision ID: a3d9e6f8b215
Revises: f2a7c9e4d816
"""

import sqlalchemy as sa
from alembic import op

revision = "a3d9e6f8b215"
down_revision = "f2a7c9e4d816"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_notification_preferences_user_id_users")),
        sa.UniqueConstraint("user_id", name=op.f("uq_notification_preferences_user_id")),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.String(500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_notifications_user_id_users")),
        sa.UniqueConstraint("user_id", "source_key", name="uq_notifications_owner_source"),
    )
    op.create_index("ix_notifications_owner_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
