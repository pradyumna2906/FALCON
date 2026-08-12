"""PostgreSQL process resources and request-scoped session management."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from falcon_api.core.config import Settings
from falcon_api.core.errors import ApplicationError


_READINESS_QUERY = text("SELECT 1")


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    """Own the engine and session factory shared by one application process."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Release every pooled connection during application shutdown."""
        await self.engine.dispose()


def create_database_resources(settings: Settings) -> DatabaseResources:
    """Create lazy PostgreSQL resources without opening a connection."""
    engine = create_async_engine(
        settings.database_url,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
        },
        hide_parameters=True,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_size=settings.db_pool_size,
        pool_timeout=settings.db_pool_timeout_seconds,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    return DatabaseResources(
        engine=engine,
        session_factory=session_factory,
    )


def database_resources_from(request: Request) -> DatabaseResources:
    """Return the process resources attached by the application lifespan."""
    return cast(DatabaseResources, request.app.state.database)


@asynccontextmanager
async def session_scope(
    resources: DatabaseResources,
) -> AsyncIterator[AsyncSession]:
    """Provide one session and roll back failed units of work."""
    session = resources.session_factory()
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for one session per request."""
    resources = database_resources_from(request)
    async with session_scope(resources) as session:
        yield session


async def assert_database_ready(
    resources: DatabaseResources,
    *,
    timeout_seconds: float,
) -> None:
    """Verify PostgreSQL with one bounded, side-effect-free query."""
    try:
        async with asyncio.timeout(timeout_seconds):
            async with resources.engine.connect() as connection:
                await connection.execute(_READINESS_QUERY)
    except Exception:
        raise ApplicationError(
            code="service_unavailable",
            message="The service is temporarily unavailable.",
            status_code=503,
        ) from None
