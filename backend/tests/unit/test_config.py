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

def test_authentication_environment_settings_are_loaded_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "AUTHENTICATION-SIGNING-SECRET-" + ("x" * 32)

    monkeypatch.setenv("FALCON_AUTH_SIGNING_SECRET", secret)
    monkeypatch.setenv(
        "FALCON_AUTH_ACCESS_TOKEN_ALGORITHM",
        "HS256",
    )
    monkeypatch.setenv(
        "FALCON_AUTH_ACCESS_TOKEN_ISSUER",
        "falcon-test-api",
    )
    monkeypatch.setenv(
        "FALCON_AUTH_ACCESS_TOKEN_AUDIENCE",
        "falcon-test-web",
    )
    monkeypatch.setenv(
        "FALCON_AUTH_ACCESS_TOKEN_LIFETIME_MINUTES",
        "20",
    )
    monkeypatch.setenv(
        "FALCON_AUTH_REFRESH_TOKEN_LIFETIME_DAYS",
        "10",
    )
    monkeypatch.setenv(
        "FALCON_AUTH_EMAIL_VERIFICATION_LIFETIME_MINUTES",
        "45",
    )
    monkeypatch.setenv(
        "FALCON_AUTH_PASSWORD_RESET_LIFETIME_MINUTES",
        "25",
    )
    monkeypatch.setenv("FALCON_AUTH_OPAQUE_TOKEN_BYTES", "48")
    monkeypatch.setenv("FALCON_AUTH_PASSWORD_MIN_LENGTH", "14")
    monkeypatch.setenv("FALCON_AUTH_PASSWORD_MAX_LENGTH", "120")

    settings = Settings(_env_file=None)

    assert (
        settings.auth_signing_secret.get_secret_value()
        == secret
    )
    assert settings.auth_access_token_algorithm == "HS256"
    assert settings.auth_access_token_issuer == "falcon-test-api"
    assert settings.auth_access_token_audience == "falcon-test-web"
    assert settings.auth_access_token_lifetime_minutes == 20
    assert settings.auth_refresh_token_lifetime_days == 10
    assert settings.auth_email_verification_lifetime_minutes == 45
    assert settings.auth_password_reset_lifetime_minutes == 25
    assert settings.auth_opaque_token_bytes == 48
    assert settings.auth_password_min_length == 14
    assert settings.auth_password_max_length == 120

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert "**********" in repr(settings)


@pytest.mark.parametrize(
    "secret",
    [
        "replace_with_a_random_secret_of_at_least_32_characters",
        "too-short",
    ],
)
def test_production_rejects_unsafe_authentication_secret(
    secret: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="strong authentication signing secret",
    ):
        Settings(
            _env_file=None,
            env=AppEnvironment.PRODUCTION,
            debug=False,
            auth_signing_secret=secret,
        )


def test_production_accepts_strong_authentication_secret() -> None:
    settings = Settings(
        _env_file=None,
        env=AppEnvironment.PRODUCTION,
        debug=False,
        auth_signing_secret="x" * 48,
        auth_delivery_encryption_key=(
            "YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmI="
        ),
    )

    assert settings.env is AppEnvironment.PRODUCTION


def test_access_token_algorithm_is_fixed() -> None:
    with pytest.raises(ValidationError):
        Settings(
            auth_access_token_algorithm="none",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_access_token_lifetime_minutes", 0),
        ("auth_access_token_lifetime_minutes", 61),
        ("auth_refresh_token_lifetime_days", 0),
        ("auth_refresh_token_lifetime_days", 31),
        ("auth_email_verification_lifetime_minutes", 4),
        ("auth_password_reset_lifetime_minutes", 121),
        ("auth_opaque_token_bytes", 31),
        ("auth_password_min_length", 11),
        ("auth_password_max_length", 129),
    ],
)
def test_invalid_authentication_limits_are_rejected(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_password_length_range_must_be_ordered() -> None:
    with pytest.raises(
        ValidationError,
        match="minimum length must not exceed maximum",
    ):
        Settings(
            auth_password_min_length=100,
            auth_password_max_length=64,
        )


@pytest.mark.parametrize(
    "field",
    [
        "auth_access_token_issuer",
        "auth_access_token_audience",
    ],
)
def test_blank_authentication_identifier_is_rejected(
    field: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="must not be blank",
    ):
        Settings(**{field: "   "})
