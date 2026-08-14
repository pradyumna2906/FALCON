"""Typed declarative base, metadata and model-mixin tests."""

from datetime import UTC, datetime
from uuid import UUID

from falcon_api.infrastructure.persistence import (
    Base,
    NAMING_CONVENTION,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    create_metadata,
    model_metadata,
    utc_now,
)
from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class _TestBase(DeclarativeBase):
    metadata = create_metadata()


class _ExampleModel(UUIDPrimaryKeyMixin, TimestampMixin, _TestBase):
    __tablename__ = "persistence_examples"

    value: Mapped[int] = mapped_column(Integer, nullable=False)


def test_base_exposes_single_empty_model_metadata() -> None:
    assert model_metadata() is Base.metadata
    assert len(Base.metadata.tables) == 0


def test_create_metadata_returns_isolated_metadata() -> None:
    first = create_metadata()
    second = create_metadata()

    assert first is not second
    assert first.naming_convention == dict(NAMING_CONVENTION)
    assert second.naming_convention == dict(NAMING_CONVENTION)


def test_naming_convention_generates_deterministic_names() -> None:
    metadata = create_metadata()

    parents = Table(
        "parents",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    children = Table(
        "children",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", ForeignKey(parents.c.id), nullable=False),
        Column("unique_value", Integer, unique=True),
        Column("indexed_value", Integer, index=True),
        CheckConstraint("unique_value > 0", name="positive_value"),
    )

    primary_key = children.primary_key
    foreign_key = next(iter(children.foreign_key_constraints))
    unique_constraint = next(
        constraint
        for constraint in children.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
    check_constraint = next(
        constraint
        for constraint in children.constraints
        if isinstance(constraint, CheckConstraint)
    )
    index = next(iter(children.indexes))

    assert primary_key.name == "pk_children"
    assert foreign_key.name == "fk_children_parent_id_parents"
    assert unique_constraint.name == "uq_children_unique_value"
    assert check_constraint.name == "ck_children_positive_value"
    assert index.name == "ix_children_indexed_value"


def test_uuid_primary_key_uses_application_callable() -> None:
    id_column = _ExampleModel.__table__.c.id

    assert id_column.primary_key is True
    assert id_column.nullable is False
    assert id_column.default is not None
    assert id_column.default.is_callable is True

    generated = id_column.default.arg(None)

    assert isinstance(generated, UUID)
    assert generated.version == 4


def test_timestamp_mixin_uses_timezone_aware_columns() -> None:
    created_column = _ExampleModel.__table__.c.created_at
    updated_column = _ExampleModel.__table__.c.updated_at

    assert created_column.nullable is False
    assert updated_column.nullable is False
    assert created_column.type.timezone is True
    assert updated_column.type.timezone is True
    assert created_column.default is not None
    assert updated_column.default is not None
    assert updated_column.onupdate is not None


def test_utc_now_returns_aware_utc_datetime() -> None:
    timestamp = utc_now()

    assert isinstance(timestamp, datetime)
    assert timestamp.tzinfo is UTC
    assert timestamp.utcoffset() is not None
