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
    monkeypatch.setenv("FALCON_DB_HOST", "database.internal")
    monkeypatch.setenv("FALCON_DB_PORT", "5544")
    monkeypatch.setenv("FALCON_DB_NAME", "falcon_env_test")
    monkeypatch.setenv("FALCON_DB_USER", "falcon_env_user")
    monkeypatch.setenv("FALCON_DB_PASSWORD", "environment-password")
    monkeypatch.setenv("FALCON_DB_POOL_SIZE", "7")
    monkeypatch.setenv("FALCON_DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("FALCON_DB_POOL_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("FALCON_DB_POOL_RECYCLE_SECONDS", "900")
    monkeypatch.setenv("FALCON_DB_CONNECT_TIMEOUT_SECONDS", "6")
    monkeypatch.setenv("FALCON_DB_READINESS_TIMEOUT_SECONDS", "1.5")

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
    assert settings.db_host == "database.internal"
    assert settings.db_port == 5544
    assert settings.db_name == "falcon_env_test"
    assert settings.db_user == "falcon_env_user"
    assert settings.db_password.get_secret_value() == "environment-password"
    assert settings.db_pool_size == 7
    assert settings.db_max_overflow == 3
    assert settings.db_pool_timeout_seconds == 4
    assert settings.db_pool_recycle_seconds == 900
    assert settings.db_connect_timeout_seconds == 6
    assert settings.db_readiness_timeout_seconds == 1.5


def test_database_url_is_structured_and_password_safe() -> None:
    settings = Settings(
        db_host="database.internal",
        db_port=5544,
        db_name="falcon_test",
        db_user="falcon_user",
        db_password="TOP-SECRET-DATABASE-PASSWORD",
    )

    rendered = settings.database_url.render_as_string()

    assert settings.database_url.drivername == "postgresql+psycopg"
    assert settings.database_url.host == "database.internal"
    assert settings.database_url.port == 5544
    assert settings.database_url.database == "falcon_test"
    assert settings.database_url.username == "falcon_user"
    assert "TOP-SECRET" not in rendered
    assert "TOP-SECRET" not in repr(settings)
    assert "***" in rendered


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


@pytest.mark.parametrize("field", ["db_host", "db_name", "db_user"])
def test_blank_database_component_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        Settings(**{field: "   "})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("db_port", 0),
        ("db_pool_size", 0),
        ("db_max_overflow", -1),
        ("db_pool_timeout_seconds", 0),
        ("db_pool_recycle_seconds", 59),
        ("db_connect_timeout_seconds", 0),
        ("db_readiness_timeout_seconds", 0),
    ],
)
def test_invalid_database_limit_is_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_settings_provider_is_cached() -> None:
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()

    assert first is second
    get_settings.cache_clear()
