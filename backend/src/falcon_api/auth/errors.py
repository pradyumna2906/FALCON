"""Authentication-domain exceptions."""


class AuthenticationError(Exception):
    """Base exception for authentication-domain failures."""


class PasswordPolicyError(AuthenticationError, ValueError):
    """Raised when a password violates the configured policy."""


class InvalidAccessTokenError(AuthenticationError):
    """Raised when an access token cannot be trusted."""
