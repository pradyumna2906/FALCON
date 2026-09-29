"""Tests for authentication clocks and password cryptography."""

from datetime import UTC

import pytest

from falcon_api.auth import PasswordPolicyError, PasswordService, SystemClock


@pytest.fixture
def password_service() -> PasswordService:
    return PasswordService(
        minimum_length=12,
        maximum_length=128,
    )


def test_system_clock_returns_timezone_aware_utc_time() -> None:
    timestamp = SystemClock().now()

    assert timestamp.tzinfo is UTC
    assert timestamp.utcoffset() is not None
    assert timestamp.utcoffset().total_seconds() == 0


def test_password_service_rejects_invalid_configuration() -> None:
    with pytest.raises(
        ValueError,
        match="Minimum password length must be positive",
    ):
        PasswordService(minimum_length=0, maximum_length=128)

    with pytest.raises(
        ValueError,
        match="Maximum password length",
    ):
        PasswordService(minimum_length=129, maximum_length=128)


def test_hash_password_creates_argon2id_hash(
    password_service: PasswordService,
) -> None:
    encoded_hash = password_service.hash_password(
        "correct horse battery staple"
    )

    assert encoded_hash.startswith("$argon2id$")
    assert "correct horse battery staple" not in encoded_hash


def test_hash_password_uses_random_salt(
    password_service: PasswordService,
) -> None:
    password = "correct horse battery staple"

    first_hash = password_service.hash_password(password)
    second_hash = password_service.hash_password(password)

    assert first_hash != second_hash
    assert password_service.verify_password(password, first_hash)
    assert password_service.verify_password(password, second_hash)


@pytest.mark.parametrize(
    "password",
    [
        "",
        "short",
        "x" * 11,
    ],
)
def test_hash_password_rejects_passwords_below_minimum_length(
    password_service: PasswordService,
    password: str,
) -> None:
    with pytest.raises(
        PasswordPolicyError,
        match="at least 12 characters",
    ):
        password_service.hash_password(password)


def test_hash_password_rejects_passwords_above_maximum_length(
    password_service: PasswordService,
) -> None:
    with pytest.raises(
        PasswordPolicyError,
        match="at most 128 characters",
    ):
        password_service.hash_password("x" * 129)


def test_password_length_counts_unicode_characters(
    password_service: PasswordService,
) -> None:
    password = "🔐" * 12

    encoded_hash = password_service.hash_password(password)

    assert password_service.verify_password(password, encoded_hash)


def test_password_whitespace_is_not_trimmed(
    password_service: PasswordService,
) -> None:
    password = "  secure password  "
    encoded_hash = password_service.hash_password(password)

    assert password_service.verify_password(password, encoded_hash)
    assert not password_service.verify_password(
        password.strip(),
        encoded_hash,
    )


def test_verify_password_rejects_incorrect_password(
    password_service: PasswordService,
) -> None:
    encoded_hash = password_service.hash_password(
        "correct horse battery staple"
    )

    assert not password_service.verify_password(
        "incorrect horse battery staple",
        encoded_hash,
    )


@pytest.mark.parametrize(
    "encoded_hash",
    [
        "",
        "not-a-password-hash",
        "$argon2id$malformed",
    ],
)
def test_verify_password_safely_rejects_malformed_hash(
    password_service: PasswordService,
    encoded_hash: str,
) -> None:
    assert not password_service.verify_password(
        "correct horse battery staple",
        encoded_hash,
    )


def test_verify_and_update_accepts_current_hash(
    password_service: PasswordService,
) -> None:
    password = "correct horse battery staple"
    encoded_hash = password_service.hash_password(password)

    verified, replacement_hash = password_service.verify_and_update(
        password,
        encoded_hash,
    )

    assert verified
    assert replacement_hash is None


def test_verify_and_update_safely_rejects_malformed_hash(
    password_service: PasswordService,
) -> None:
    verified, replacement_hash = password_service.verify_and_update(
        "correct horse battery staple",
        "not-a-password-hash",
    )

    assert not verified
    assert replacement_hash is None
