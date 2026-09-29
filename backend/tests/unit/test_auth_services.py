"""Tests for configuration-backed authentication cryptography."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from falcon_api.auth import (
    PasswordPolicyError,
    create_authentication_cryptography,
    verify_opaque_token,
)
from falcon_api.core.config import Settings


_FIXED_TIME = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)


@dataclass
class FixedClock:
    current_time: datetime

    def now(self) -> datetime:
        return self.current_time


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        auth_signing_secret="x" * 48,
        auth_access_token_algorithm="HS256",
        auth_access_token_issuer="falcon-api",
        auth_access_token_audience="falcon-web",
        auth_access_token_lifetime_minutes=15,
        auth_opaque_token_bytes=32,
        auth_password_min_length=12,
        auth_password_max_length=128,
    )


def test_factory_builds_working_password_service(
    settings: Settings,
) -> None:
    services = create_authentication_cryptography(settings)
    password = "correct horse battery staple"

    encoded_hash = services.passwords.hash_password(password)

    assert encoded_hash.startswith("$argon2id$")
    assert services.passwords.verify_password(password, encoded_hash)


def test_factory_applies_configured_password_minimum(
    settings: Settings,
) -> None:
    settings = settings.model_copy(
        update={"auth_password_min_length": 16}
    )
    services = create_authentication_cryptography(settings)

    with pytest.raises(
        PasswordPolicyError,
        match="at least 16 characters",
    ):
        services.passwords.hash_password("twelve-chars")


def test_factory_applies_configured_password_maximum(
    settings: Settings,
) -> None:
    settings = settings.model_copy(
        update={"auth_password_max_length": 16}
    )
    services = create_authentication_cryptography(settings)

    with pytest.raises(
        PasswordPolicyError,
        match="at most 16 characters",
    ):
        services.passwords.hash_password("x" * 17)


def test_factory_builds_working_access_token_service(
    settings: Settings,
) -> None:
    clock = FixedClock(_FIXED_TIME)
    services = create_authentication_cryptography(
        settings,
        clock=clock,
    )
    user_id = uuid4()
    session_id = uuid4()

    encoded = services.access_tokens.create(
        user_id=user_id,
        session_id=session_id,
    )
    claims = services.access_tokens.decode(encoded.value)

    assert claims.user_id == user_id
    assert claims.session_id == session_id
    assert claims.issued_at == _FIXED_TIME
    assert claims.expires_at == _FIXED_TIME + timedelta(minutes=15)


def test_factory_applies_configured_access_token_lifetime(
    settings: Settings,
) -> None:
    settings = settings.model_copy(
        update={"auth_access_token_lifetime_minutes": 5}
    )
    clock = FixedClock(_FIXED_TIME)
    services = create_authentication_cryptography(
        settings,
        clock=clock,
    )

    encoded = services.access_tokens.create(
        user_id=uuid4(),
        session_id=uuid4(),
    )

    assert encoded.claims.expires_at == (
        _FIXED_TIME + timedelta(minutes=5)
    )


def test_factory_generates_configured_opaque_token(
    settings: Settings,
) -> None:
    settings = settings.model_copy(
        update={"auth_opaque_token_bytes": 48}
    )
    services = create_authentication_cryptography(settings)

    token = services.generate_opaque_token()

    assert len(token.value) >= 64
    assert verify_opaque_token(token.value, token.digest)


def test_authentication_cryptography_container_is_immutable(
    settings: Settings,
) -> None:
    services = create_authentication_cryptography(settings)

    with pytest.raises(AttributeError):
        services.opaque_token_bytes = 64  # type: ignore[misc]
