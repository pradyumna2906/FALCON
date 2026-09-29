"""Real PostgreSQL readiness and transactional-session integration tests."""

import asyncio
import os

import pytest
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
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


def test_transaction_scope_against_real_postgresql() -> None:
    """Verify successful commit and failed-work rollback using PostgreSQL."""
    resources = create_database_resources(_integration_settings())

    async def exercise_transactions() -> None:
        try:
            async with resources.engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        CREATE TEMPORARY TABLE falcon_session_scope_probe (
                            value INTEGER PRIMARY KEY
                        ) ON COMMIT PRESERVE ROWS
                        """
                    )
                )

            async with transaction_scope(resources.session_factory) as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO falcon_session_scope_probe (value)
                        VALUES (1)
                        """
                    )
                )

            async with resources.engine.connect() as connection:
                committed_result = await connection.execute(
                    text(
                        """
                        SELECT value
                        FROM falcon_session_scope_probe
                        ORDER BY value
                        """
                    )
                )
                assert committed_result.scalars().all() == [1]

            with pytest.raises(RuntimeError, match="force rollback"):
                async with transaction_scope(
                    resources.session_factory
                ) as session:
                    await session.execute(
                        text(
                            """
                            INSERT INTO falcon_session_scope_probe (value)
                            VALUES (2)
                            """
                        )
                    )
                    raise RuntimeError("force rollback")

            async with resources.engine.connect() as connection:
                rollback_result = await connection.execute(
                    text(
                        """
                        SELECT value
                        FROM falcon_session_scope_probe
                        ORDER BY value
                        """
                    )
                )
                assert rollback_result.scalars().all() == [1]
        finally:
            await resources.dispose()

    asyncio.run(
        exercise_transactions(),
        loop_factory=create_psycopg_compatible_event_loop,
    )
