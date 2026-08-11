"""Application factory tests."""

from falcon_api import __version__
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.main import create_app
from fastapi.testclient import TestClient


def test_factory_uses_injected_settings(test_settings: Settings) -> None:
    application = create_app(test_settings)

    assert application.state.settings is test_settings
    assert application.title == test_settings.app_name
    assert application.version == __version__


def test_factory_returns_isolated_applications(test_settings: Settings) -> None:
    assert create_app(test_settings) is not create_app(test_settings)


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
