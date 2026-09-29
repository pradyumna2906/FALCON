"""Generation and hashing of high-entropy opaque authentication tokens."""

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe


_MINIMUM_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class OpaqueToken:
    """Raw opaque token paired with its storage-safe SHA-256 digest."""

    value: str
    digest: str


def hash_opaque_token(token: str) -> str:
    """Return the lowercase SHA-256 digest of an opaque token."""
    return sha256(token.encode("utf-8")).hexdigest()


def generate_opaque_token(*, byte_count: int = _MINIMUM_TOKEN_BYTES) -> OpaqueToken:
    """Generate a URL-safe token containing at least 256 bits of entropy."""
    if byte_count < _MINIMUM_TOKEN_BYTES:
        raise ValueError(
            f"Opaque tokens must use at least {_MINIMUM_TOKEN_BYTES} random bytes."
        )

    value = token_urlsafe(byte_count)

    return OpaqueToken(
        value=value,
        digest=hash_opaque_token(value),
    )


def verify_opaque_token(token: str, expected_digest: str) -> bool:
    """Compare an opaque token with its stored digest in constant time."""
    if len(expected_digest) != 64:
        return False

    try:
        int(expected_digest, 16)
    except ValueError:
        return False

    actual_digest = hash_opaque_token(token)

    return compare_digest(
        actual_digest,
        expected_digest.lower(),
    )
