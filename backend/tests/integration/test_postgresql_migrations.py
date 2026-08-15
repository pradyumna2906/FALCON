"""Real PostgreSQL Alembic migration lifecycle tests."""

import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from falcon_api.core.config import AppEnvironment, Settings


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_BASELINE_REVISION = "25efb498276a"
_SCHEMA_REVISION = "a1b1833784e5"


def integration_settings() -> Settings:
    """Load root environment values with deterministic test behavior."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


def create_alembic_config() -> Config:
    """Return the repository Alembic configuration."""
    return Config(str(_ALEMBIC_CONFIG))


def current_database_revision(settings: Settings) -> str | None:
    """Read the revision stored in PostgreSQL."""
    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        connect_timeout=settings.db_connect_timeout_seconds,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            row = cursor.fetchone()

    return None if row is None else row[0]


def test_schema_upgrade_downgrade_lifecycle_against_postgresql() -> None:
    """Verify repeatable schema upgrades and complete downgrades."""
    config = create_alembic_config()
    settings = integration_settings()

    command.downgrade(config, "base")

    try:
        command.upgrade(config, "head")
        assert current_database_revision(settings) == _SCHEMA_REVISION

        command.upgrade(config, "head")
        assert current_database_revision(settings) == _SCHEMA_REVISION

        command.downgrade(config, _BASELINE_REVISION)
        assert current_database_revision(settings) == _BASELINE_REVISION

        command.upgrade(config, "head")
        assert current_database_revision(settings) == _SCHEMA_REVISION
    finally:
        command.downgrade(config, "base")

    assert current_database_revision(settings) is None
