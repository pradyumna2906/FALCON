"""Tests for encrypted authentication delivery payloads."""

from cryptography.fernet import Fernet
import pytest

from falcon_api.auth.delivery import (
    AuthenticationDeliveryCipher,
    EncryptedDeliveryPayload,
)


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture
def cipher(encryption_key: str) -> AuthenticationDeliveryCipher:
    return AuthenticationDeliveryCipher(
        encryption_key=encryption_key,
        key_id="test-key-v1",
    )


def test_email_verification_payload_round_trip(
    cipher: AuthenticationDeliveryCipher,
) -> None:
    encrypted = cipher.encrypt_email_verification(
        email="user@example.com",
        token="raw-secret-verification-token",
    )
    decrypted = cipher.decrypt_email_verification(encrypted)

    assert decrypted.email == "user@example.com"
    assert decrypted.token == "raw-secret-verification-token"
    assert encrypted.key_id == "test-key-v1"


def test_ciphertext_does_not_contain_sensitive_values(
    cipher: AuthenticationDeliveryCipher,
) -> None:
    email = "private-user@example.com"
    token = "raw-secret-verification-token"

    encrypted = cipher.encrypt_email_verification(
        email=email,
        token=token,
    )

    assert email.encode() not in encrypted.ciphertext
    assert token.encode() not in encrypted.ciphertext


def test_same_message_produces_distinct_ciphertext(
    cipher: AuthenticationDeliveryCipher,
) -> None:
    first = cipher.encrypt_email_verification(
        email="user@example.com",
        token="raw-secret-verification-token",
    )
    second = cipher.encrypt_email_verification(
        email="user@example.com",
        token="raw-secret-verification-token",
    )

    assert first.ciphertext != second.ciphertext


def test_wrong_key_cannot_decrypt_payload(
    cipher: AuthenticationDeliveryCipher,
) -> None:
    encrypted = cipher.encrypt_email_verification(
        email="user@example.com",
        token="raw-secret-verification-token",
    )
    other = AuthenticationDeliveryCipher(
        encryption_key=Fernet.generate_key().decode("ascii"),
        key_id="test-key-v1",
    )

    with pytest.raises(
        ValueError,
        match="payload is invalid",
    ):
        other.decrypt_email_verification(encrypted)


def test_wrong_key_identifier_is_rejected(
    cipher: AuthenticationDeliveryCipher,
) -> None:
    encrypted = cipher.encrypt_email_verification(
        email="user@example.com",
        token="raw-secret-verification-token",
    )
    wrong_identifier = EncryptedDeliveryPayload(
        ciphertext=encrypted.ciphertext,
        key_id="different-key",
    )

    with pytest.raises(
        ValueError,
        match="payload is invalid",
    ):
        cipher.decrypt_email_verification(wrong_identifier)


def test_tampered_ciphertext_is_rejected(
    cipher: AuthenticationDeliveryCipher,
) -> None:
    encrypted = cipher.encrypt_email_verification(
        email="user@example.com",
        token="raw-secret-verification-token",
    )
    tampered = EncryptedDeliveryPayload(
        ciphertext=encrypted.ciphertext[:-1] + b"x",
        key_id=encrypted.key_id,
    )

    with pytest.raises(
        ValueError,
        match="payload is invalid",
    ):
        cipher.decrypt_email_verification(tampered)


@pytest.mark.parametrize(
    ("encryption_key", "key_id"),
    [
        ("invalid-key", "test-key-v1"),
        ("é" * 44, "test-key-v1"),
        (Fernet.generate_key().decode("ascii"), " "),
    ],
)
def test_cipher_rejects_invalid_configuration(
    encryption_key: str,
    key_id: str,
) -> None:
    with pytest.raises(ValueError):
        AuthenticationDeliveryCipher(
            encryption_key=encryption_key,
            key_id=key_id,
        )
