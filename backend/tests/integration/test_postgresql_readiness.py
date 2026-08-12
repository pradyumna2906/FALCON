"""Real PostgreSQL readiness integration test."""

import asyncio
import os

import pytest
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.infrastructure.database import (
    create_database_resources,
    session_scope,
)
from falcon_api.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import text


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]


def _integration_settings() -> Settings:
    return Settings(
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


def test_readiness_against_real_postgresql() -> None:
    """Exercise the production driver and engine against the Compose service."""
    with TestClient(
        create_app(_integration_settings()),
        backend_options={
            "loop_factory": create_psycopg_compatible_event_loop,
        },
    ) as client:
        response = client.get(
            "/health/ready",
            headers={"X-Request-ID": "postgresql-integration-id"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "falcon-api"}
    assert response.headers["X-Request-ID"] == "postgresql-integration-id"


def test_async_session_against_real_postgresql() -> None:
    """Exercise the production async session factory without modifying data."""
    resources = create_database_resources(_integration_settings())

    async def execute_probe() -> None:
        try:
            async with session_scope(resources) as session:
                result = await session.execute(text("SELECT 1"))
                assert result.scalar_one() == 1
        finally:
            await resources.dispose()

    asyncio.run(
        execute_probe(),
        loop_factory=create_psycopg_compatible_event_loop,
    )
