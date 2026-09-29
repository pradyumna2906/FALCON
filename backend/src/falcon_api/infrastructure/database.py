"""PostgreSQL process resources and request-scoped session management."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

from falcon_api.core.config import Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.persistence import (
    SessionFactory,
    create_session_factory,
    transaction_scope,
)
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine


_READINESS_QUERY = text("SELECT 1")


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    """Own the engine and session factory shared by one application process."""

    engine: AsyncEngine
    session_factory: SessionFactory

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

    return DatabaseResources(
        engine=engine,
        session_factory=create_session_factory(engine),
    )


def database_resources_from(request: Request) -> DatabaseResources:
    """Return the process resources attached by the application lifespan."""
    return cast(DatabaseResources, request.app.state.database)


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one transactional database session per request."""
    resources = database_resources_from(request)

    async with transaction_scope(resources.session_factory) as session:
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
