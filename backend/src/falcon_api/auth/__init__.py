"""Authentication and account-security primitives."""

from falcon_api.auth.access_tokens import (
    AccessTokenClaims,
    AccessTokenService,
    EncodedAccessToken,
)
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.auth.delivery import (
    AuthenticationDeliveryCipher,
    EmailVerificationDelivery,
    EncryptedDeliveryPayload,
)
from falcon_api.auth.errors import (
    AuthenticationError,
    InvalidAccessTokenError,
    PasswordPolicyError,
)
from falcon_api.auth.opaque_tokens import (
    OpaqueToken,
    generate_opaque_token,
    hash_opaque_token,
    verify_opaque_token,
)
from falcon_api.auth.passwords import PasswordService
from falcon_api.auth.services import (
    AuthenticationCryptography,
    create_authentication_cryptography,
)
from falcon_api.auth.registration import (
    RegistrationCommand,
    RegistrationResult,
    RegistrationService,
)

__all__ = [
    "AccessTokenClaims",
    "AccessTokenService",
    "AuthenticationCryptography",
    "AuthenticationDeliveryCipher",
    "AuthenticationError",
    "Clock",
    "EmailVerificationDelivery",
    "EncodedAccessToken",
    "EncryptedDeliveryPayload",
    "InvalidAccessTokenError",
    "OpaqueToken",
    "PasswordPolicyError",
    "PasswordService",
    "SystemClock",
    "create_authentication_cryptography",
    "generate_opaque_token",
    "hash_opaque_token",
    "verify_opaque_token",
    "RegistrationCommand",
    "RegistrationResult",
    "RegistrationService",
]
