"""Typed application configuration."""

from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
