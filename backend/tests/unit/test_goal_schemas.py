"""Strict public goal request and response schema tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from falcon_api.schemas.goals import (
    ContributionCreateRequest,
    GoalCreateRequest,
    GoalUpdateRequest,
)


def _payload() -> dict[str, object]:
    return {
        "name": "  Education fund  ",
        "goal_type": "education",
        "target_amount": "200000.0000",
        "starting_amount": "25000.0000",
        "currency": "inr",
        "target_date": "2028-06-01",
        "priority": "high",
        "description": "  Semester fees  ",
    }


def test_create_normalizes_public_display_values() -> None:
    request = GoalCreateRequest.model_validate(_payload())

    assert request.name == "Education fund"
    assert request.currency == "INR"
    assert request.target_amount == Decimal("200000.0000")
    assert request.target_date == date(2028, 6, 1)
    assert request.description == "Semester fees"


def test_create_uses_safe_defaults_and_blank_description() -> None:
    payload = _payload()
    payload.pop("currency")
    payload.pop("starting_amount")
    payload.pop("priority")
    payload["description"] = "   "

    request = GoalCreateRequest.model_validate(payload)

    assert request.currency is None
    assert request.starting_amount == Decimal("0")
    assert request.priority.value == "medium"
    assert request.description is None


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": str(uuid4())},
        {"status": "completed"},
        {"target_amount": "0"},
        {"starting_amount": "200000.00001"},
        {"currency": "₹"},
        {"name": ""},
        {"description": "x" * 1_001},
    ],
)
def test_create_rejects_server_owned_or_invalid_values(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GoalCreateRequest.model_validate({**_payload(), **change})


def test_create_rejects_starting_amount_above_target() -> None:
    with pytest.raises(ValidationError, match="Starting amount"):
        GoalCreateRequest.model_validate(
            {
                **_payload(),
                "target_amount": "1000",
                "starting_amount": "1001",
            }
        )


def test_update_tracks_partial_fields_and_allows_description_clear() -> None:
    request = GoalUpdateRequest.model_validate(
        {"priority": "critical", "description": None}
    )

    assert request.model_fields_set == {"priority", "description"}
    assert request.description is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"priority": None},
        {"currency": None},
        {"unknown": "value"},
        {"target_amount": "100", "starting_amount": "101"},
    ],
)
def test_update_rejects_empty_null_or_invalid_changes(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GoalUpdateRequest.model_validate(payload)


def test_manual_and_transaction_contribution_contracts_are_distinct() -> None:
    manual = ContributionCreateRequest.model_validate(
        {
            "source_type": "manual",
            "amount": "1250.5000",
            "contribution_date": "2026-09-01",
            "note": "  Deposit  ",
        }
    )
    transaction_id = uuid4()
    transaction = ContributionCreateRequest.model_validate(
        {
            "source_type": "transaction",
            "amount": "500",
            "transaction_id": str(transaction_id),
        }
    )

    assert manual.note == "Deposit"
    assert manual.contribution_date == date(2026, 9, 1)
    assert transaction.transaction_id == transaction_id
    assert transaction.contribution_date is None


@pytest.mark.parametrize(
    "payload",
    [
        {"source_type": "manual", "amount": "100"},
        {
            "source_type": "manual",
            "amount": "100",
            "contribution_date": "2026-09-01",
            "transaction_id": str(uuid4()),
        },
        {
            "source_type": "transaction",
            "amount": "100",
            "transaction_id": str(uuid4()),
            "contribution_date": "2026-09-01",
        },
        {"source_type": "transaction", "amount": "100"},
        {
            "source_type": "opening_balance",
            "amount": "0",
            "contribution_date": "2026-09-01",
        },
    ],
)
def test_contribution_schema_rejects_invalid_source_or_amount(payload) -> None:
    with pytest.raises(ValidationError):
        ContributionCreateRequest.model_validate(payload)
