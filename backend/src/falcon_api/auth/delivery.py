"""Authenticated encryption for durable authentication delivery payloads."""

from dataclasses import dataclass
import json
from typing import Final

from cryptography.fernet import Fernet, InvalidToken


_EMAIL_VERIFICATION_PURPOSE: Final = "email_verification"


@dataclass(frozen=True, slots=True)
class EncryptedDeliveryPayload:
    """Ciphertext and the identifier of the key that encrypted it."""

    ciphertext: bytes
    key_id: str


@dataclass(frozen=True, slots=True)
class EmailVerificationDelivery:
    """Trusted email-verification delivery content."""

    email: str
    token: str


class AuthenticationDeliveryCipher:
    """Encrypt authentication messages before they cross persistence."""

    def __init__(
        self,
        *,
        encryption_key: str,
        key_id: str,
    ) -> None:
        if not key_id.strip():
            raise ValueError("Delivery encryption key ID must not be blank.")

        try:
            self._fernet = Fernet(encryption_key.encode("ascii"))
        except (UnicodeEncodeError, ValueError):
            raise ValueError(
                "Delivery encryption key must be a valid Fernet key."
            ) from None

        self._key_id = key_id

    def encrypt_email_verification(
        self,
        *,
        email: str,
        token: str,
    ) -> EncryptedDeliveryPayload:
        """Encrypt one verification message for durable delivery."""
        plaintext = json.dumps(
            {
                "email": email,
                "purpose": _EMAIL_VERIFICATION_PURPOSE,
                "token": token,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        return EncryptedDeliveryPayload(
            ciphertext=self._fernet.encrypt(plaintext),
            key_id=self._key_id,
        )

    def decrypt_email_verification(
        self,
        payload: EncryptedDeliveryPayload,
    ) -> EmailVerificationDelivery:
        """Decrypt and strictly validate one delivery payload."""
        if payload.key_id != self._key_id:
            raise ValueError("Authentication delivery payload is invalid.")

        try:
            decoded = self._fernet.decrypt(payload.ciphertext)
            content = json.loads(decoded.decode("utf-8"))
        except (
            InvalidToken,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            raise ValueError(
                "Authentication delivery payload is invalid."
            ) from None

        if (
            not isinstance(content, dict)
            or set(content) != {"email", "purpose", "token"}
            or content.get("purpose") != _EMAIL_VERIFICATION_PURPOSE
            or not isinstance(content.get("email"), str)
            or not isinstance(content.get("token"), str)
        ):
            raise ValueError(
                "Authentication delivery payload is invalid."
            )

        return EmailVerificationDelivery(
            email=content["email"],
            token=content["token"],
        )
