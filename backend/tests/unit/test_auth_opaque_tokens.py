"""Tests for high-entropy opaque authentication tokens."""

import re

import pytest

from falcon_api.auth import (
    OpaqueToken,
    generate_opaque_token,
    hash_opaque_token,
    verify_opaque_token,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def test_generate_opaque_token_returns_value_and_digest() -> None:
    token = generate_opaque_token()

    assert isinstance(token, OpaqueToken)
    assert token.value
    assert _SHA256_PATTERN.fullmatch(token.digest)
    assert token.digest == hash_opaque_token(token.value)


def test_generate_opaque_token_uses_at_least_256_bits() -> None:
    token = generate_opaque_token(byte_count=32)

    # Base64url encoding of 32 random bytes produces 43 characters.
    assert len(token.value) >= 43


def test_generate_opaque_token_returns_unique_values() -> None:
    tokens = {generate_opaque_token().value for _ in range(20)}

    assert len(tokens) == 20


def test_generate_opaque_token_returns_unique_digests() -> None:
    digests = {generate_opaque_token().digest for _ in range(20)}

    assert len(digests) == 20


@pytest.mark.parametrize(
    "byte_count",
    [
        -1,
        0,
        16,
        31,
    ],
)
def test_generate_opaque_token_rejects_insufficient_entropy(
    byte_count: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="at least 32 random bytes",
    ):
        generate_opaque_token(byte_count=byte_count)


def test_hash_opaque_token_is_deterministic() -> None:
    token = "example-opaque-authentication-token"

    first_digest = hash_opaque_token(token)
    second_digest = hash_opaque_token(token)

    assert first_digest == second_digest
    assert _SHA256_PATTERN.fullmatch(first_digest)


def test_hash_opaque_token_does_not_store_raw_token() -> None:
    token = "example-opaque-authentication-token"
    digest = hash_opaque_token(token)

    assert token not in digest


def test_verify_opaque_token_accepts_matching_token() -> None:
    token = generate_opaque_token()

    assert verify_opaque_token(token.value, token.digest)


def test_verify_opaque_token_accepts_uppercase_digest() -> None:
    token = generate_opaque_token()

    assert verify_opaque_token(
        token.value,
        token.digest.upper(),
    )


def test_verify_opaque_token_rejects_different_token() -> None:
    token = generate_opaque_token()
    different_token = generate_opaque_token()

    assert not verify_opaque_token(
        different_token.value,
        token.digest,
    )


@pytest.mark.parametrize(
    "invalid_digest",
    [
        "",
        "abc123",
        "g" * 64,
        "0" * 63,
        "0" * 65,
    ],
)
def test_verify_opaque_token_rejects_invalid_digest(
    invalid_digest: str,
) -> None:
    assert not verify_opaque_token(
        "example-opaque-authentication-token",
        invalid_digest,
    )


def test_opaque_token_is_immutable() -> None:
    token = generate_opaque_token()

    with pytest.raises(AttributeError):
        token.value = "replacement"  # type: ignore[misc]
