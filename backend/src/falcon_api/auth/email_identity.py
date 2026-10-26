"""Validation and canonical normalization of authentication email identities."""

from email_validator import EmailNotValidError, validate_email


_ASCII_WHITESPACE = " \t\r\n\f\v"
_MAXIMUM_EMAIL_LENGTH = 320


class InvalidEmailAddressError(ValueError):
    """Raised when an email identity cannot be accepted."""


def normalize_email_address(value: str) -> str:
    """Return one stable lowercase email identity without DNS access."""
    candidate = value.strip(_ASCII_WHITESPACE)

    try:
        validation = validate_email(
            candidate,
            allow_smtputf8=True,
            check_deliverability=False,
        )
    except EmailNotValidError:
        raise InvalidEmailAddressError(
            "A valid email address is required."
        ) from None

    normalized = validation.normalized.lower()

    if len(normalized) > _MAXIMUM_EMAIL_LENGTH:
        raise InvalidEmailAddressError(
            "A valid email address is required."
        )

    return normalized
