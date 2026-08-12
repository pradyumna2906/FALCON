"""Shared backend test fixtures."""

from collections.abc import Iterator

import pytest
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def test_settings() -> Settings:
    """Return deterministic settings that never read the developer's .env."""
    return Settings(
        app_name="FALCON API",
        env=AppEnvironment.TEST,
        debug=False,
        api_host="127.0.0.1",
        api_port=8000,
        docs_enabled=True,
        cors_allowed_origins=("https://app.falcon.test",),
        db_host="127.0.0.1",
        db_port=5433,
        db_name="falcon_test",
        db_user="falcon_test",
        db_password="test-only-database-password",
        db_pool_size=2,
        db_max_overflow=1,
        db_pool_timeout_seconds=1,
        db_pool_recycle_seconds=300,
        db_connect_timeout_seconds=1,
        db_readiness_timeout_seconds=0.1,
    )


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """Run the application lifespan around each API test."""
    with TestClient(create_app(test_settings)) as test_client:
        yield test_client
