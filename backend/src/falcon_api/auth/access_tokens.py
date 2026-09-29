"""Strict creation and validation of signed JWT access tokens."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import jwt
from jwt import PyJWTError

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.auth.errors import InvalidAccessTokenError


_ACCESS_TOKEN_TYPE: Final = "access"
_REQUIRED_CLAIMS: Final = frozenset(
    {
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
)


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Trusted claims extracted from a validated access token."""

    user_id: UUID
    session_id: UUID
    token_id: UUID
    issued_at: datetime
    not_before: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EncodedAccessToken:
    """Encoded access token and its trusted claims."""

    value: str
    claims: AccessTokenClaims


class AccessTokenService:
    """Create and validate short-lived signed JWT access tokens."""

    def __init__(
        self,
        *,
        signing_secret: str,
        algorithm: str,
        issuer: str,
        audience: str,
        lifetime: timedelta,
        clock: Clock | None = None,
    ) -> None:
        if len(signing_secret) < 32:
            raise ValueError(
                "The access-token signing secret must contain at least 32 characters."
            )

        if algorithm != "HS256":
            raise ValueError("Only the HS256 access-token algorithm is supported.")

        if not issuer.strip():
            raise ValueError("The access-token issuer must not be blank.")

        if not audience.strip():
            raise ValueError("The access-token audience must not be blank.")

        if lifetime <= timedelta(0):
            raise ValueError("The access-token lifetime must be positive.")

        self._signing_secret = signing_secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._lifetime = lifetime
        self._clock = clock or SystemClock()

    def create(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
    ) -> EncodedAccessToken:
        """Create a signed access token for one user session."""
        issued_at = _require_utc(self._clock.now())
        expires_at = issued_at + self._lifetime
        token_id = uuid4()

        claims = AccessTokenClaims(
            user_id=user_id,
            session_id=session_id,
            token_id=token_id,
            issued_at=issued_at,
            not_before=issued_at,
            expires_at=expires_at,
        )

        payload = {
            "aud": self._audience,
            "exp": expires_at,
            "iat": issued_at,
            "iss": self._issuer,
            "jti": str(token_id),
            "nbf": issued_at,
            "sid": str(session_id),
            "sub": str(user_id),
            "typ": _ACCESS_TOKEN_TYPE,
        }

        encoded = jwt.encode(
            payload,
            self._signing_secret,
            algorithm=self._algorithm,
        )

        return EncodedAccessToken(
            value=encoded,
            claims=claims,
        )

    def decode(self, token: str) -> AccessTokenClaims:
        """Validate a token and return only trusted typed claims."""
        try:
            payload = jwt.decode(
                token,
                self._signing_secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": sorted(_REQUIRED_CLAIMS),
                    "strict_aud": True,
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )

            if set(payload) != _REQUIRED_CLAIMS:
                raise InvalidAccessTokenError("Invalid access token.")

            if payload["typ"] != _ACCESS_TOKEN_TYPE:
                raise InvalidAccessTokenError("Invalid access token.")

            issued_at = _numeric_date(payload["iat"])
            not_before = _numeric_date(payload["nbf"])
            expires_at = _numeric_date(payload["exp"])
            current_time = _require_utc(self._clock.now())

            if issued_at > current_time:
                raise InvalidAccessTokenError("Invalid access token.")

            if not_before > current_time:
                raise InvalidAccessTokenError("Invalid access token.")

            if not_before < issued_at:
                raise InvalidAccessTokenError("Invalid access token.")

            if expires_at <= issued_at:
                raise InvalidAccessTokenError("Invalid access token.")

            if expires_at <= current_time:
                raise InvalidAccessTokenError("Invalid access token.")

            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                session_id=UUID(payload["sid"]),
                token_id=UUID(payload["jti"]),
                issued_at=issued_at,
                not_before=not_before,
                expires_at=expires_at,
            )
        except InvalidAccessTokenError:
            raise
        except (OverflowError, PyJWTError, TypeError, ValueError) as error:
            raise InvalidAccessTokenError("Invalid access token.") from error


def _numeric_date(value: object) -> datetime:
    """Convert a strict JWT NumericDate value to a UTC datetime."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("JWT timestamp must be numeric.")

    return datetime.fromtimestamp(value, UTC)


def _require_utc(value: datetime) -> datetime:
    """Require a timezone-aware timestamp and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Authentication timestamps must be timezone-aware.")

    return value.astimezone(UTC)
