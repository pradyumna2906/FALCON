"""Alembic environment for asynchronous FALCON migrations."""

import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from falcon_api.core.config import Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.infrastructure.persistence.base import model_metadata
from falcon_api.models import register_models
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

register_models()
target_metadata = model_metadata()

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPOSITORY_ROOT / ".env"


def get_database_url() -> str:
    """Load the unredacted database URL only for the migration process."""
    settings = Settings(_env_file=_ENV_FILE)
    return settings.database_url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_server_default=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    """Run migrations through an established synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=True,
        compare_type=True,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Create a temporary async engine and execute migrations."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(
        run_migrations_online(),
        loop_factory=create_psycopg_compatible_event_loop,
    )
