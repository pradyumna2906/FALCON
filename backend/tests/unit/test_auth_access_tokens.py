"""Tests for strict JWT access-token cryptography."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest

from falcon_api.auth import (
    AccessTokenService,
    InvalidAccessTokenError,
)


_SIGNING_SECRET = "x" * 48
_ISSUER = "falcon-api"
_AUDIENCE = "falcon-web"
_LIFETIME = timedelta(minutes=15)
_INITIAL_TIME = datetime(2026, 8, 15, 6, 30, tzinfo=UTC)


@dataclass
class FixedClock:
    current_time: datetime

    def now(self) -> datetime:
        return self.current_time


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(_INITIAL_TIME)


@pytest.fixture
def token_service(clock: FixedClock) -> AccessTokenService:
    return AccessTokenService(
        signing_secret=_SIGNING_SECRET,
        algorithm="HS256",
        issuer=_ISSUER,
        audience=_AUDIENCE,
        lifetime=_LIFETIME,
        clock=clock,
    )


def test_create_returns_signed_access_token(
    token_service: AccessTokenService,
) -> None:
    user_id = uuid4()
    session_id = uuid4()

    token = token_service.create(
        user_id=user_id,
        session_id=session_id,
    )

    assert token.value
    assert token.claims.user_id == user_id
    assert token.claims.session_id == session_id
    assert token.claims.issued_at == _INITIAL_TIME
    assert token.claims.not_before == _INITIAL_TIME
    assert token.claims.expires_at == _INITIAL_TIME + _LIFETIME


def test_create_uses_unique_token_identifiers(
    token_service: AccessTokenService,
) -> None:
    user_id = uuid4()
    session_id = uuid4()

    first = token_service.create(
        user_id=user_id,
        session_id=session_id,
    )
    second = token_service.create(
        user_id=user_id,
        session_id=session_id,
    )

    assert first.claims.token_id != second.claims.token_id
    assert first.value != second.value


def test_decode_returns_typed_trusted_claims(
    token_service: AccessTokenService,
) -> None:
    user_id = uuid4()
    session_id = uuid4()
    encoded = token_service.create(
        user_id=user_id,
        session_id=session_id,
    )

    claims = token_service.decode(encoded.value)

    assert claims == encoded.claims
    assert isinstance(claims.user_id, UUID)
    assert isinstance(claims.session_id, UUID)
    assert isinstance(claims.token_id, UUID)


def test_encoded_token_contains_only_approved_claims(
    token_service: AccessTokenService,
) -> None:
    encoded = token_service.create(
        user_id=uuid4(),
        session_id=uuid4(),
    )

    payload = jwt.decode(
        encoded.value,
        options={
            "verify_signature": False,
            "verify_exp": False,
            "verify_aud": False,
        },
    )

    assert set(payload) == {
        "aud",
        "exp",
        "iat",
        "iss",
        "jti",
        "nbf",
        "sid",
        "sub",
        "typ",
    }
    assert payload["typ"] == "access"


def test_decode_rejects_expired_token(
    token_service: AccessTokenService,
    clock: FixedClock,
) -> None:
    encoded = token_service.create(
        user_id=uuid4(),
        session_id=uuid4(),
    )
    clock.current_time = _INITIAL_TIME + _LIFETIME

    with pytest.raises(
        InvalidAccessTokenError,
        match="Invalid access token",
    ):
        token_service.decode(encoded.value)


def test_decode_accepts_token_before_expiry(
    token_service: AccessTokenService,
    clock: FixedClock,
) -> None:
    encoded = token_service.create(
        user_id=uuid4(),
        session_id=uuid4(),
    )
    clock.current_time = (
        _INITIAL_TIME + _LIFETIME - timedelta(seconds=1)
    )

    claims = token_service.decode(encoded.value)

    assert claims == encoded.claims


def test_decode_rejects_wrong_signing_secret(
    token_service: AccessTokenService,
    clock: FixedClock,
) -> None:
    encoded = token_service.create(
        user_id=uuid4(),
        session_id=uuid4(),
    )
    other_service = AccessTokenService(
        signing_secret="y" * 48,
        algorithm="HS256",
        issuer=_ISSUER,
        audience=_AUDIENCE,
        lifetime=_LIFETIME,
        clock=clock,
    )

    with pytest.raises(InvalidAccessTokenError):
        other_service.decode(encoded.value)


@pytest.mark.parametrize(
    ("issuer", "audience"),
    [
        ("different-issuer", _AUDIENCE),
        (_ISSUER, "different-audience"),
    ],
)
def test_decode_rejects_wrong_issuer_or_audience(
    token_service: AccessTokenService,
    clock: FixedClock,
    issuer: str,
    audience: str,
) -> None:
    encoded = token_service.create(
        user_id=uuid4(),
        session_id=uuid4(),
    )
    other_service = AccessTokenService(
        signing_secret=_SIGNING_SECRET,
        algorithm="HS256",
        issuer=issuer,
        audience=audience,
        lifetime=_LIFETIME,
        clock=clock,
    )

    with pytest.raises(InvalidAccessTokenError):
        other_service.decode(encoded.value)


def test_decode_rejects_malformed_token(
    token_service: AccessTokenService,
) -> None:
    with pytest.raises(
        InvalidAccessTokenError,
        match="Invalid access token",
    ):
        token_service.decode("not-a-jwt")


@pytest.mark.parametrize(
    "invalid_identifier",
    [
        "",
        "not-a-uuid",
        "00000000",
    ],
)
def test_decode_rejects_invalid_uuid_claim(
    token_service: AccessTokenService,
    invalid_identifier: str,
) -> None:
    payload = _valid_payload()
    payload["sub"] = invalid_identifier
    encoded = _encode(payload)

    with pytest.raises(InvalidAccessTokenError):
        token_service.decode(encoded)


def test_decode_rejects_non_access_token_type(
    token_service: AccessTokenService,
) -> None:
    payload = _valid_payload()
    payload["typ"] = "refresh"
    encoded = _encode(payload)

    with pytest.raises(InvalidAccessTokenError):
        token_service.decode(encoded)


def test_decode_rejects_unapproved_extra_claim(
    token_service: AccessTokenService,
) -> None:
    payload = _valid_payload()
    payload["email"] = "user@example.com"
    encoded = _encode(payload)

    with pytest.raises(InvalidAccessTokenError):
        token_service.decode(encoded)


def test_decode_rejects_missing_required_claim(
    token_service: AccessTokenService,
) -> None:
    payload = _valid_payload()
    del payload["sid"]
    encoded = _encode(payload)

    with pytest.raises(InvalidAccessTokenError):
        token_service.decode(encoded)


def test_decode_rejects_future_token(
    token_service: AccessTokenService,
) -> None:
    payload = _valid_payload()
    future_time = _INITIAL_TIME + timedelta(minutes=1)
    payload["iat"] = future_time
    payload["nbf"] = future_time
    payload["exp"] = future_time + _LIFETIME
    encoded = _encode(payload)

    with pytest.raises(InvalidAccessTokenError):
        token_service.decode(encoded)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("iat", "not-numeric"),
        ("nbf", True),
        ("exp", None),
    ],
)
def test_decode_rejects_invalid_numeric_date(
    token_service: AccessTokenService,
    field: str,
    invalid_value: object,
) -> None:
    payload = _valid_payload()
    payload[field] = invalid_value
    encoded = _encode(payload)

    with pytest.raises(InvalidAccessTokenError):
        token_service.decode(encoded)


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "signing_secret": "too-short",
            "algorithm": "HS256",
            "issuer": _ISSUER,
            "audience": _AUDIENCE,
            "lifetime": _LIFETIME,
        },
        {
            "signing_secret": _SIGNING_SECRET,
            "algorithm": "HS512",
            "issuer": _ISSUER,
            "audience": _AUDIENCE,
            "lifetime": _LIFETIME,
        },
        {
            "signing_secret": _SIGNING_SECRET,
            "algorithm": "HS256",
            "issuer": " ",
            "audience": _AUDIENCE,
            "lifetime": _LIFETIME,
        },
        {
            "signing_secret": _SIGNING_SECRET,
            "algorithm": "HS256",
            "issuer": _ISSUER,
            "audience": " ",
            "lifetime": _LIFETIME,
        },
        {
            "signing_secret": _SIGNING_SECRET,
            "algorithm": "HS256",
            "issuer": _ISSUER,
            "audience": _AUDIENCE,
            "lifetime": timedelta(0),
        },
    ],
)
def test_service_rejects_unsafe_configuration(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        AccessTokenService(**arguments)  # type: ignore[arg-type]


def _valid_payload() -> dict[str, object]:
    return {
        "aud": _AUDIENCE,
        "exp": _INITIAL_TIME + _LIFETIME,
        "iat": _INITIAL_TIME,
        "iss": _ISSUER,
        "jti": str(uuid4()),
        "nbf": _INITIAL_TIME,
        "sid": str(uuid4()),
        "sub": str(uuid4()),
        "typ": "access",
    }


def _encode(payload: dict[str, object]) -> str:
    return jwt.encode(
        payload,
        _SIGNING_SECRET,
        algorithm="HS256",
    )
