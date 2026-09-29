"""Unit tests for strict transaction API schemas."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from falcon_api.models.enums import (
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.schemas.transaction import (
    ManualTransactionCreateRequest,
    TransactionListQuery,
    TransactionPageResponse,
    TransactionResponse,
    TransferCreateRequest,
)
from pydantic import ValidationError


def _manual_payload() -> dict[str, object]:
    return {
        "account_id": uuid4(),
        "category_id": uuid4(),
        "transaction_type": "expense",
        "amount": "1250.5000",
        "transaction_date": "2026-08-20",
        "description": "  Monthly groceries  ",
        "merchant_name": "  Local Market  ",
    }


def _response() -> TransactionResponse:
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    return TransactionResponse(
        id=uuid4(),
        account_id=uuid4(),
        category_id=None,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("1250.5000"),
        transaction_date=date(2026, 8, 20),
        description="Monthly groceries",
        merchant_name="Local Market",
        source_type=TransactionSourceType.MANUAL,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
        created_at=now,
        updated_at=now,
    )


def test_manual_request_accepts_and_normalizes_valid_values() -> None:
    request = ManualTransactionCreateRequest.model_validate(
        _manual_payload()
    )

    assert request.amount == Decimal("1250.5000")
    assert request.description == "Monthly groceries"
    assert request.merchant_name == "Local Market"


@pytest.mark.parametrize("amount", ["0", "-1", "1000000000000000"])
def test_manual_request_rejects_invalid_amount(amount: str) -> None:
    payload = _manual_payload()
    payload["amount"] = amount

    with pytest.raises(ValidationError):
        ManualTransactionCreateRequest.model_validate(payload)


@pytest.mark.parametrize("transaction_type", ["transfer", "adjustment"])
def test_manual_request_rejects_non_manual_transaction_types(
    transaction_type: str,
) -> None:
    payload = _manual_payload()
    payload["transaction_type"] = transaction_type

    with pytest.raises(ValidationError):
        ManualTransactionCreateRequest.model_validate(payload)


def test_manual_request_rejects_server_owned_fields() -> None:
    payload = _manual_payload()
    payload["user_id"] = uuid4()
    payload["status"] = "posted"

    with pytest.raises(ValidationError) as info:
        ManualTransactionCreateRequest.model_validate(payload)

    locations = {error["loc"] for error in info.value.errors()}
    assert ("user_id",) in locations
    assert ("status",) in locations


def test_blank_optional_merchant_normalizes_to_none() -> None:
    payload = _manual_payload()
    payload["merchant_name"] = "   "

    request = ManualTransactionCreateRequest.model_validate(payload)

    assert request.merchant_name is None


def test_transfer_requires_two_distinct_accounts() -> None:
    account_id = uuid4()

    with pytest.raises(ValidationError):
        TransferCreateRequest(
            source_account_id=account_id,
            destination_account_id=account_id,
            amount=Decimal("500"),
            transaction_date=date(2026, 8, 20),
            description="Move to savings",
        )


def test_transfer_accepts_two_distinct_owned_account_references() -> None:
    request = TransferCreateRequest(
        source_account_id=uuid4(),
        destination_account_id=uuid4(),
        amount=Decimal("500"),
        transaction_date=date(2026, 8, 20),
        description="Move to savings",
    )

    assert request.source_account_id != request.destination_account_id


def test_transaction_query_enforces_bounds_and_date_order() -> None:
    assert TransactionListQuery().limit == 50

    with pytest.raises(ValidationError):
        TransactionListQuery(limit=101)
    with pytest.raises(ValidationError):
        TransactionListQuery(
            date_from=date(2026, 8, 21),
            date_to=date(2026, 8, 20),
        )
    with pytest.raises(ValidationError):
        TransactionListQuery(cursor="not a cursor")


def test_transaction_response_excludes_private_ledger_fields() -> None:
    properties = set(TransactionResponse.model_json_schema()["properties"])

    assert "user_id" not in properties
    assert "external_source_hash" not in properties
    assert "import_job_id" not in properties
    assert "transfer_group_id" not in properties


def test_transaction_response_requires_positive_public_magnitude() -> None:
    payload = _response().model_dump()
    payload["amount"] = Decimal("-1")

    with pytest.raises(ValidationError):
        TransactionResponse.model_validate(payload)


def test_transaction_page_and_nested_items_are_immutable() -> None:
    transaction = _response()
    page = TransactionPageResponse(
        items=(transaction,),
        next_cursor=None,
    )

    with pytest.raises(ValidationError):
        page.next_cursor = "next"  # type: ignore[misc]
    assert page.items == (transaction,)
