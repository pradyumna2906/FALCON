"""Typed declarative base and reusable persistence mixins."""

from datetime import UTC, datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from falcon_api.infrastructure.persistence.conventions import create_metadata
from falcon_api.infrastructure.persistence.types import (
    UTCDateTime,
    UUIDPrimaryKey,
)


def utc_now() -> datetime:
    """Return a timezone-aware current UTC timestamp."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative root for every FALCON SQLAlchemy model."""

    metadata = create_metadata()


class UUIDPrimaryKeyMixin:
    """Provide an application-generated immutable UUIDv4 primary key."""

    id: Mapped[UUIDPrimaryKey]


class TimestampMixin:
    """Provide timezone-aware creation and last-update timestamps."""

    created_at: Mapped[UTCDateTime] = mapped_column(
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[UTCDateTime] = mapped_column(
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


def model_metadata() -> MetaData:
    """Return the single metadata object used by models and migrations."""
    return Base.metadata
