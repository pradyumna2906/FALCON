"""Configuration-backed authentication cryptography services."""

from dataclasses import dataclass
from datetime import timedelta

from falcon_api.auth.access_tokens import AccessTokenService
from falcon_api.auth.clock import Clock
from falcon_api.auth.opaque_tokens import OpaqueToken, generate_opaque_token
from falcon_api.auth.passwords import PasswordService
from falcon_api.core.config import Settings


@dataclass(frozen=True, slots=True)
class AuthenticationCryptography:
    """Application-facing authentication cryptography services."""

    passwords: PasswordService
    access_tokens: AccessTokenService
    opaque_token_bytes: int

    def generate_opaque_token(self) -> OpaqueToken:
        """Generate an opaque token using the configured entropy."""
        return generate_opaque_token(
            byte_count=self.opaque_token_bytes,
        )


def create_authentication_cryptography(
    settings: Settings,
    *,
    clock: Clock | None = None,
) -> AuthenticationCryptography:
    """Build authentication cryptography from validated settings."""
    return AuthenticationCryptography(
        passwords=PasswordService(
            minimum_length=settings.auth_password_min_length,
            maximum_length=settings.auth_password_max_length,
        ),
        access_tokens=AccessTokenService(
            signing_secret=settings.auth_signing_secret.get_secret_value(),
            algorithm=settings.auth_access_token_algorithm,
            issuer=settings.auth_access_token_issuer,
            audience=settings.auth_access_token_audience,
            lifetime=timedelta(
                minutes=settings.auth_access_token_lifetime_minutes
            ),
            clock=clock,
        ),
        opaque_token_bytes=settings.auth_opaque_token_bytes,
    )
