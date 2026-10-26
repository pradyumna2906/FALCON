"""Async SQLAlchemy session creation and transaction boundaries."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from falcon_api.core.errors import CommittedApplicationError


SessionFactory = async_sessionmaker[AsyncSession]


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    """Create the process-wide session factory for one managed engine."""
    return async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


@asynccontextmanager
async def transaction_scope(
    session_factory: SessionFactory,
) -> AsyncIterator[AsyncSession]:
    """Commit successful work and explicitly marked security failures."""
    session = session_factory()

    try:
        async with session.begin() as transaction:
            try:
                yield session
            except CommittedApplicationError:
                await transaction.commit()
                raise
    finally:
        await session.close()
