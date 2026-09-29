"""Password policy enforcement and Argon2id hashing."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from falcon_api.auth.errors import PasswordPolicyError


class PasswordService:
    """Validate, hash, and verify authentication passwords."""

    def __init__(
        self,
        *,
        minimum_length: int,
        maximum_length: int,
        password_hash: PasswordHash | None = None,
    ) -> None:
        if minimum_length < 1:
            raise ValueError("Minimum password length must be positive.")

        if maximum_length < minimum_length:
            raise ValueError(
                "Maximum password length must not be less than the minimum."
            )

        self._minimum_length = minimum_length
        self._maximum_length = maximum_length
        self._password_hash = password_hash or PasswordHash.recommended()

    def validate_password(self, password: str) -> None:
        """Reject passwords outside the configured Unicode length range."""
        password_length = len(password)

        if password_length < self._minimum_length:
            raise PasswordPolicyError(
                f"Password must contain at least {self._minimum_length} characters."
            )

        if password_length > self._maximum_length:
            raise PasswordPolicyError(
                f"Password must contain at most {self._maximum_length} characters."
            )

    def hash_password(self, password: str) -> str:
        """Validate and hash a password using the recommended Argon2id settings."""
        self.validate_password(password)
        return self._password_hash.hash(password)

    def verify_password(
        self,
        password: str,
        encoded_hash: str,
    ) -> bool:
        """Verify a password without exposing malformed-hash errors."""
        try:
            return self._password_hash.verify(password, encoded_hash)
        except (UnknownHashError, ValueError):
            return False

    def verify_and_update(
        self,
        password: str,
        encoded_hash: str,
    ) -> tuple[bool, str | None]:
        """Verify a password and return a replacement hash when required."""
        try:
            return self._password_hash.verify_and_update(
                password,
                encoded_hash,
            )
        except (UnknownHashError, ValueError):
            return False, None
