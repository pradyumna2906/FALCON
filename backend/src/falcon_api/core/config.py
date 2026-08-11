"""Typed application configuration."""

from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import (
    AnyHttpUrl,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


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

    @model_validator(mode="after")
    def reject_unsafe_production_debug(self) -> Self:
        """Prevent debug tracebacks from being enabled in production."""
        if self.env is AppEnvironment.PRODUCTION and self.debug:
            raise ValueError("Debug mode must be disabled in production.")
        return self

    @property
    def api_docs_enabled(self) -> bool:
        """Enable docs outside production unless explicitly configured."""
        if self.docs_enabled is not None:
            return self.docs_enabled
        return self.env is not AppEnvironment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
