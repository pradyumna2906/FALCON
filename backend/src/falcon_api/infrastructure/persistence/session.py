"""Async SQLAlchemy session creation and transaction boundaries."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)


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
    """Commit one successful unit of work and roll back failed work."""
    session = session_factory()

    try:
        async with session.begin():
            yield session
    finally:
        await session.close()
