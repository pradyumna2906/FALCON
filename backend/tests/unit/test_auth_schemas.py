"""Tests for authentication registration and verification schemas."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from falcon_api.schemas.auth import (
    EmailVerificationConfirmation,
    EmailVerificationRequest,
    GenericAcceptedResponse,
    RegisteredUserResponse,
    RegistrationRequest,
)


def test_registration_request_normalizes_identity_fields() -> None:
    request = RegistrationRequest(
        email=" User@Example.COM ",
        password="correct horse battery staple",
        display_name="  Pradyumna  ",
        timezone="Asia/Kolkata",
        default_currency="INR",
    )

    assert request.email == "user@example.com"
    assert request.password == "correct horse battery staple"
    assert request.display_name == "Pradyumna"
    assert request.timezone == "Asia/Kolkata"
    assert request.default_currency == "INR"


def test_registration_request_has_india_first_defaults() -> None:
    request = RegistrationRequest(
        email="user@example.com",
        password="correct horse battery staple",
    )

    assert request.timezone == "Asia/Kolkata"
    assert request.default_currency == "INR"
    assert request.display_name is None


def test_registration_does_not_trim_or_modify_password() -> None:
    password = "  secure password  "
    request = RegistrationRequest(
        email="user@example.com",
        password=password,
    )

    assert request.password == password


@pytest.mark.parametrize(
    "password",
    [
        "x" * 11,
        "x" * 129,
    ],
)
def test_registration_rejects_password_outside_policy(
    password: str,
) -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(
            email="user@example.com",
            password=password,
        )


@pytest.mark.parametrize(
    "display_name",
    [
        "",
        " ",
        "\t\r\n",
    ],
)
def test_registration_rejects_blank_display_name(
    display_name: str,
) -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(
            email="user@example.com",
            password="correct horse battery staple",
            display_name=display_name,
        )


def test_registration_rejects_unknown_timezone() -> None:
    with pytest.raises(
        ValidationError,
        match="valid IANA identifier",
    ):
        RegistrationRequest(
            email="user@example.com",
            password="correct horse battery staple",
            timezone="Invalid/Timezone",
        )


@pytest.mark.parametrize(
    "currency",
    [
        "inr",
        "IN",
        "INDR",
        "123",
    ],
)
def test_registration_rejects_invalid_currency(
    currency: str,
) -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(
            email="user@example.com",
            password="correct horse battery staple",
            default_currency=currency,
        )


def test_registration_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(
            email="user@example.com",
            password="correct horse battery staple",
            password_confirmation="correct horse battery staple",
        )


def test_registered_user_response_is_minimal() -> None:
    user_id = uuid4()
    response = RegisteredUserResponse(
        id=user_id,
        email="user@example.com",
    )

    assert response.model_dump() == {
        "id": user_id,
        "email": "user@example.com",
        "email_verified": False,
    }


def test_email_verification_request_normalizes_email() -> None:
    request = EmailVerificationRequest(
        email=" USER@EXAMPLE.COM ",
    )

    assert request.email == "user@example.com"


def test_verification_confirmation_accepts_url_safe_token() -> None:
    token = "A" * 43
    request = EmailVerificationConfirmation(token=token)

    assert request.token == token


@pytest.mark.parametrize(
    "token",
    [
        "",
        "a" * 42,
        "contains spaces" + ("x" * 32),
        "contains.periods" + ("x" * 32),
    ],
)
def test_verification_confirmation_rejects_invalid_token(
    token: str,
) -> None:
    with pytest.raises(ValidationError):
        EmailVerificationConfirmation(token=token)


def test_generic_accepted_response_has_fixed_contract() -> None:
    response = GenericAcceptedResponse()

    assert response.model_dump() == {"status": "accepted"}


def test_authentication_schemas_are_immutable() -> None:
    request = EmailVerificationRequest(email="user@example.com")

    with pytest.raises(ValidationError):
        request.email = "different@example.com"
