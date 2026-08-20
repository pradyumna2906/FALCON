"""Tests for public account and category setup schemas."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from falcon_api.schemas.ledger import (
    AccountCreateRequest,
    AccountResponse,
    CategoryResponse,
)
from pydantic import ValidationError


def _account_payload() -> dict[str, object]:
    return {
        "name": "Primary Bank",
        "account_type": "bank",
        "institution_name": "State Bank",
        "masked_reference": "•••• 1234",
        "currency": "inr",
        "opening_balance": "25000.5000",
        "opening_balance_date": "2026-08-20",
    }


def test_account_create_normalizes_public_values() -> None:
    request = AccountCreateRequest(**_account_payload())

    assert request.name == "Primary Bank"
    assert request.currency == "INR"
    assert request.opening_balance == Decimal("25000.5000")


def test_account_create_defaults_optional_values() -> None:
    request = AccountCreateRequest(
        name="Cash",
        account_type="cash",
        opening_balance_date=date(2026, 8, 20),
        institution_name="  ",
        masked_reference="",
    )

    assert request.currency is None
    assert request.opening_balance == Decimal("0")
    assert request.institution_name is None
    assert request.masked_reference is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", " "),
        ("account_type", "crypto"),
        ("currency", "RUPEE"),
        ("opening_balance", "1000000000000000.0000"),
        ("opening_balance", "1.00001"),
    ],
)
def test_account_create_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    payload = _account_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        AccountCreateRequest(**payload)


def test_account_create_rejects_server_owned_values() -> None:
    for field in ("id", "user_id", "created_at", "archived_at"):
        payload = {**_account_payload(), field: "client-controlled"}
        with pytest.raises(ValidationError):
            AccountCreateRequest(**payload)


def test_public_responses_exclude_ownership_and_internal_names() -> None:
    now = datetime.now(UTC)
    account = AccountResponse(
        id=uuid4(),
        name="Cash",
        account_type="cash",
        institution_name=None,
        masked_reference=None,
        currency="INR",
        opening_balance="100.0000",
        opening_balance_date=date(2026, 8, 20),
        created_at=now,
        updated_at=now,
    )
    category = CategoryResponse(
        id=uuid4(),
        name="Groceries",
        kind="expense",
        parent_id=None,
        is_system=True,
        display_order=10,
    )

    assert "user_id" not in AccountResponse.model_fields
    assert "archived_at" not in AccountResponse.model_fields
    assert "normalized_name" not in CategoryResponse.model_fields
    assert "user_id" not in CategoryResponse.model_fields


def test_ledger_schemas_are_immutable() -> None:
    request = AccountCreateRequest(**_account_payload())

    with pytest.raises(ValidationError):
        request.name = "Changed"
