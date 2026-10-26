"""Persist owner inbox state and opt-in notification preferences."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from falcon_api.infrastructure.persistence import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "source_key", name="uq_notifications_owner_source"),
        Index("ix_notifications_owner_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_key: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(String(500))
    read_at: Mapped[UTCDateTime | None] = mapped_column(nullable=True)
    dismissed_at: Mapped[UTCDateTime | None] = mapped_column(nullable=True)
