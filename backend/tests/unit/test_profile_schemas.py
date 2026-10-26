"""Tests for the public financial-profile schemas."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from falcon_api.models.enums import ProfileCompletionStatus
from falcon_api.schemas.profile import (
    FinancialProfilePutRequest,
    FinancialProfileResponse,
)


def _valid_request_data() -> dict[str, object]:
    return {
        "income_pattern": "salaried",
        "income_stability": "stable",
        "has_household_responsibilities": True,
        "dependant_count": 2,
        "emergency_fund_target_months": "6.00",
    }


def test_profile_request_accepts_complete_planning_context() -> None:
    request = FinancialProfilePutRequest(**_valid_request_data())

    assert request.income_pattern == "salaried"
    assert request.income_stability == "stable"
    assert request.has_household_responsibilities is True
    assert request.dependant_count == 2
    assert request.emergency_fund_target_months == Decimal("6.00")


def test_profile_request_accepts_draft_context() -> None:
    request = FinancialProfilePutRequest(
        income_pattern=None,
        income_stability=None,
        has_household_responsibilities=False,
        dependant_count=0,
    )

    assert request.income_pattern is None
    assert request.income_stability is None
    assert request.emergency_fund_target_months is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("income_pattern", "commission_only"),
        ("income_stability", "guaranteed"),
        ("dependant_count", -1),
        ("dependant_count", 51),
        ("emergency_fund_target_months", "-0.01"),
        ("emergency_fund_target_months", "60.01"),
        ("emergency_fund_target_months", "1.234"),
    ],
)
def test_profile_request_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    data = _valid_request_data()
    data[field] = value

    with pytest.raises(ValidationError):
        FinancialProfilePutRequest(**data)


def test_profile_request_rejects_dependants_without_responsibility() -> None:
    data = _valid_request_data()
    data["has_household_responsibilities"] = False

    with pytest.raises(
        ValidationError,
        match="Dependant count must be zero",
    ):
        FinancialProfilePutRequest(**data)


@pytest.mark.parametrize(
    "server_owned_field",
    [
        "id",
        "user_id",
        "completion_status",
        "created_at",
        "updated_at",
    ],
)
def test_profile_request_rejects_server_owned_fields(
    server_owned_field: str,
) -> None:
    data = _valid_request_data()
    data[server_owned_field] = "client-controlled"

    with pytest.raises(ValidationError):
        FinancialProfilePutRequest(**data)


def test_profile_request_requires_replacement_fields() -> None:
    for required_field in (
        "income_pattern",
        "income_stability",
        "has_household_responsibilities",
        "dependant_count",
    ):
        data = _valid_request_data()
        del data[required_field]

        with pytest.raises(ValidationError):
            FinancialProfilePutRequest(**data)


def test_profile_response_contains_only_public_profile_data() -> None:
    now = datetime.now(UTC)
    profile_id = uuid4()
    response = FinancialProfileResponse(
        id=profile_id,
        income_pattern="mixed",
        income_stability="variable",
        has_household_responsibilities=True,
        dependant_count=1,
        emergency_fund_target_months=Decimal("3.50"),
        completion_status=ProfileCompletionStatus.COMPLETE,
        created_at=now,
        updated_at=now,
    )

    assert response.model_dump() == {
        "id": profile_id,
        "income_pattern": "mixed",
        "income_stability": "variable",
        "has_household_responsibilities": True,
        "dependant_count": 1,
        "emergency_fund_target_months": Decimal("3.50"),
        "completion_status": "complete",
        "created_at": now,
        "updated_at": now,
    }
    assert "user_id" not in FinancialProfileResponse.model_fields


def test_profile_schemas_are_immutable() -> None:
    request = FinancialProfilePutRequest(**_valid_request_data())

    with pytest.raises(ValidationError):
        request.dependant_count = 3
