"""Deterministic SQLAlchemy naming conventions for database objects."""

from types import MappingProxyType

from sqlalchemy import MetaData


NAMING_CONVENTION = MappingProxyType(
    {
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    }
)


def create_metadata() -> MetaData:
    """Return isolated metadata using FALCON's stable naming convention."""
    return MetaData(naming_convention=dict(NAMING_CONVENTION))
