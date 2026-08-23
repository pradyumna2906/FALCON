"""Typed application configuration."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from cryptography.fernet import Fernet
from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_AUTH_SECRET_PLACEHOLDER = (
    "replace_with_a_random_secret_of_at_least_32_characters"
)
_AUTH_DELIVERY_KEY_PLACEHOLDER = (
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
_DEFAULT_CLASSIFICATION_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[4] / "ml" / "artifacts" / "classification"
)
_CLASSIFICATION_VERSION_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,63}$"
class AppEnvironment(StrEnum):
    """Supported deployment environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Immutable FALCON settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FALCON_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "FALCON API"
    env: AppEnvironment = AppEnvironment.DEVELOPMENT
    debug: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    docs_enabled: bool | None = None
    cors_allowed_origins: tuple[str, ...] = ()
    auth_signing_secret: SecretStr = SecretStr(
        _AUTH_SECRET_PLACEHOLDER,
    )
    auth_access_token_algorithm: Literal["HS256"] = "HS256"
    auth_access_token_issuer: str = Field(
        default="falcon-api",
        min_length=1,
        max_length=128,
    )
    auth_access_token_audience: str = Field(
        default="falcon-web",
        min_length=1,
        max_length=128,
    )
    auth_access_token_lifetime_minutes: int = Field(
        default=15,
        ge=1,
        le=60,
    )
    auth_refresh_token_lifetime_days: int = Field(
        default=7,
        ge=1,
        le=30,
    )
    auth_email_verification_lifetime_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
    )
    auth_password_reset_lifetime_minutes: int = Field(
        default=15,
        ge=5,
        le=120,
    )
    auth_opaque_token_bytes: int = Field(
        default=32,
        ge=32,
        le=64,
    )
    auth_delivery_encryption_key: SecretStr = SecretStr(
        _AUTH_DELIVERY_KEY_PLACEHOLDER,
    )
    auth_delivery_encryption_key_id: str = Field(
        default="local-development-v1",
        min_length=1,
        max_length=64,
    )
    auth_password_min_length: int = Field(
        default=12,
        ge=12,
        le=128,
    )
    auth_password_max_length: int = Field(
        default=128,
        ge=12,
        le=128,
    )
    db_host: str = Field(default="127.0.0.1", min_length=1, max_length=253)
    db_port: int = Field(default=5433, ge=1, le=65535)
    db_name: str = Field(default="falcon", min_length=1, max_length=63)
    db_user: str = Field(default="falcon_dev", min_length=1, max_length=63)
    db_password: SecretStr = SecretStr(
        "replace_with_a_strong_local_password",
    )
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    classification_artifact_root: Path = _DEFAULT_CLASSIFICATION_ARTIFACT_ROOT
    classification_model_version: str = Field(
        default="classification_2026_1_demo.1",
        pattern=_CLASSIFICATION_VERSION_PATTERN,
    )

    @field_validator("db_host", "db_name", "db_user")
    @classmethod
    def reject_blank_database_components(cls, value: str) -> str:
        """Reject database URL components that contain only whitespace."""
        if not value.strip():
            raise ValueError("Database connection components must not be blank.")
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_allowed_origins(
        cls,
        origins: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Accept only unique, exact HTTP(S) browser origins."""
        normalized_origins: list[str] = []

        for candidate in origins:
            if candidate == "*":
                raise ValueError("CORS origins must not contain a wildcard.")

            try:
                parsed = _HTTP_URL_ADAPTER.validate_python(candidate)
            except ValidationError as exc:
                raise ValueError(
                    "CORS origins must be valid HTTP(S) origins.",
                ) from exc

            if parsed.username is not None or parsed.password is not None:
                raise ValueError("CORS origins must not contain credentials.")
            if parsed.path not in (None, "", "/"):
                raise ValueError("CORS origins must not contain a path.")
            if parsed.query is not None or parsed.fragment is not None:
                raise ValueError(
                    "CORS origins must not contain a query or fragment.",
                )

            default_port = 80 if parsed.scheme == "http" else 443
            authority = parsed.host
            if parsed.port != default_port:
                authority = f"{authority}:{parsed.port}"
            normalized = f"{parsed.scheme}://{authority}"

            if normalized in normalized_origins:
                raise ValueError("CORS origins must be unique.")
            normalized_origins.append(normalized)

        return tuple(normalized_origins)
    @field_validator(
        "auth_access_token_issuer",
        "auth_access_token_audience",
    )
    @classmethod
    def reject_blank_authentication_identifiers(
        cls,
        value: str,
    ) -> str:
        """Reject blank JWT issuer and audience identifiers."""
        if not value.strip():
            raise ValueError(
                "Authentication identifiers must not be blank.",
            )
        return value
    @field_validator("auth_delivery_encryption_key")
    @classmethod
    def validate_authentication_delivery_key(
        cls,
        value: SecretStr,
    ) -> SecretStr:
        """Require a valid URL-safe 32-byte Fernet key."""
        try:
            Fernet(value.get_secret_value().encode("ascii"))
        except (UnicodeEncodeError, ValueError):
            raise ValueError(
                "Authentication delivery encryption key is invalid.",
            ) from None

        return value

    @field_validator("auth_delivery_encryption_key_id")
    @classmethod
    def reject_blank_delivery_key_id(cls, value: str) -> str:
        """Require a stable nonblank delivery encryption-key identifier."""
        if not value.strip():
            raise ValueError(
                "Authentication delivery encryption key ID must not be blank.",
            )

        return value
    @model_validator(mode="after")
    def validate_cross_field_security(self) -> Self:
        """Reject unsafe production and authentication combinations."""
        if self.auth_password_min_length > self.auth_password_max_length:
            raise ValueError(
                "Password minimum length must not exceed maximum length.",
            )

        if self.env is AppEnvironment.PRODUCTION:
            if self.debug:
                raise ValueError(
                    "Debug mode must be disabled in production.",
                )

            signing_secret = self.auth_signing_secret.get_secret_value()

            if (
                signing_secret == _AUTH_SECRET_PLACEHOLDER
                or len(signing_secret) < 32
            ):
                raise ValueError(
                    "Production requires a strong authentication "
                    "signing secret.",
                )
            delivery_key = (
                self.auth_delivery_encryption_key.get_secret_value()
            )

            if delivery_key == _AUTH_DELIVERY_KEY_PLACEHOLDER:
                raise ValueError(
                    "Production requires an independent authentication "
                    "delivery encryption key.",
                )

        return self

    @property
    def api_docs_enabled(self) -> bool:
        """Enable docs outside production unless explicitly configured."""
        if self.docs_enabled is not None:
            return self.docs_enabled
        return self.env is not AppEnvironment.PRODUCTION

    @property
    def database_url(self) -> URL:
        """Build a structured URL whose normal rendering redacts the password."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
