"""Tests for canonical authentication email identities."""

import pytest

from falcon_api.auth.email_identity import (
    InvalidEmailAddressError,
    normalize_email_address,
)


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("User@Example.COM", "user@example.com"),
        (" user@example.com ", "user@example.com"),
        ("\tUSER@EXAMPLE.COM\r\n", "user@example.com"),
        ("first.last+tag@example.com", "first.last+tag@example.com"),
        ("user@例え.テスト", "user@例え.テスト"),
    ],
)
def test_normalize_email_address_returns_canonical_identity(
    submitted: str,
    expected: str,
) -> None:
    assert normalize_email_address(submitted) == expected


@pytest.mark.parametrize(
    "submitted",
    [
        "",
        "   ",
        "not-an-email",
        "@example.com",
        "user@",
        "user@example",
        "User Name <user@example.com>",
        "user example@example.com",
    ],
)
def test_normalize_email_address_rejects_invalid_identity(
    submitted: str,
) -> None:
    with pytest.raises(
        InvalidEmailAddressError,
        match="valid email address",
    ):
        normalize_email_address(submitted)


def test_invalid_email_error_does_not_reflect_submitted_value() -> None:
    submitted = "private-invalid-address"

    with pytest.raises(InvalidEmailAddressError) as exc_info:
        normalize_email_address(submitted)

    assert submitted not in str(exc_info.value)
