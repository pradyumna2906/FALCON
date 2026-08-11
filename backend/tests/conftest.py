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
    )


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """Run the application lifespan around each API test."""
    with TestClient(create_app(test_settings)) as test_client:
        yield test_client
