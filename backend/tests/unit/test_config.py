"""Settings contract tests."""

import pytest
from falcon_api.core.config import AppEnvironment, Settings, get_settings
from pydantic import ValidationError


def test_prefixed_environment_variables_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FALCON_ENV", "test")
    monkeypatch.setenv("FALCON_DEBUG", "false")
    monkeypatch.setenv("FALCON_API_HOST", "0.0.0.0")
    monkeypatch.setenv("FALCON_API_PORT", "8123")
    monkeypatch.setenv("FALCON_DOCS_ENABLED", "false")

    settings = Settings()

    assert settings.env is AppEnvironment.TEST
    assert settings.debug is False
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 8123
    assert settings.docs_enabled is False


def test_settings_are_immutable(test_settings: Settings) -> None:
    with pytest.raises(ValidationError, match="Instance is frozen"):
        test_settings.debug = True  # type: ignore[misc]


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="Debug mode must be disabled"):
        Settings(
            env=AppEnvironment.PRODUCTION,
            debug=True,
        )


def test_api_port_must_be_valid() -> None:
    with pytest.raises(ValidationError):
        Settings(api_port=0)


def test_settings_provider_is_cached() -> None:
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()

    assert first is second
    get_settings.cache_clear()
