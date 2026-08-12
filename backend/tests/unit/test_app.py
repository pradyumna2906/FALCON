"""Application factory tests."""

from typing import cast
from unittest.mock import Mock

from falcon_api import __version__
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.infrastructure.database import DatabaseResources
from falcon_api.main import DatabaseFactory, create_app
from fastapi.testclient import TestClient


def test_factory_uses_injected_settings(test_settings: Settings) -> None:
    application = create_app(test_settings)

    assert application.state.settings is test_settings
    assert application.title == test_settings.app_name
    assert application.version == __version__


def test_factory_returns_isolated_applications(test_settings: Settings) -> None:
    assert create_app(test_settings) is not create_app(test_settings)


def test_lifespan_owns_one_database_resource_set(
    test_settings: Settings,
) -> None:
    resources = Mock(spec=DatabaseResources)
    factory = Mock(return_value=resources)
    application = create_app(
        test_settings,
        database_factory=cast(DatabaseFactory, factory),
    )

    with TestClient(application):
        assert application.state.database is resources
        factory.assert_called_once_with(test_settings)

    resources.dispose.assert_awaited_once_with()


def test_development_documentation_is_available() -> None:
    settings = Settings(
        env=AppEnvironment.DEVELOPMENT,
        docs_enabled=None,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_production_documentation_is_disabled_by_default() -> None:
    settings = Settings(
        env=AppEnvironment.PRODUCTION,
        debug=False,
        docs_enabled=None,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_production_documentation_requires_explicit_enablement() -> None:
    settings = Settings(
        env=AppEnvironment.PRODUCTION,
        debug=False,
        docs_enabled=True,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 200
