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
    monkeypatch.setenv(
        "FALCON_CORS_ALLOWED_ORIGINS",
        '["https://app.falcon.example", "http://localhost:5173"]',
    )

    settings = Settings()

    assert settings.env is AppEnvironment.TEST
    assert settings.debug is False
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 8123
    assert settings.docs_enabled is False
    assert settings.cors_allowed_origins == (
        "https://app.falcon.example",
        "http://localhost:5173",
    )


def test_cors_origins_are_normalized() -> None:
    settings = Settings(
        cors_allowed_origins=(
            "HTTPS://APP.FALCON.EXAMPLE:443/",
            "http://localhost:80",
        ),
    )

    assert settings.cors_allowed_origins == (
        "https://app.falcon.example",
        "http://localhost",
    )


@pytest.mark.parametrize(
    ("origin", "message"),
    [
        ("*", "must not contain a wildcard"),
        ("not-an-origin", "valid HTTP\\(S\\) origins"),
        ("ftp://app.falcon.example", "valid HTTP\\(S\\) origins"),
        ("https://user@app.falcon.example", "must not contain credentials"),
        ("https://app.falcon.example/private", "must not contain a path"),
        (
            "https://app.falcon.example?mode=test",
            "must not contain a query or fragment",
        ),
        (
            "https://app.falcon.example#private",
            "must not contain a query or fragment",
        ),
    ],
)
def test_unsafe_cors_origin_is_rejected(origin: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(cors_allowed_origins=(origin,))


def test_duplicate_normalized_cors_origins_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        Settings(
            cors_allowed_origins=(
                "https://app.falcon.example",
                "https://APP.FALCON.EXAMPLE:443/",
            ),
        )


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
