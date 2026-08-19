"""Contract tests for the Phase 4 financial-profile boundary."""

from pathlib import Path

from falcon_api.schemas.profile import (
    FinancialProfilePutRequest,
    FinancialProfileResponse,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMPLEMENTATION_DOCUMENT = (
    _REPOSITORY_ROOT
    / "docs"
    / "financial-profile"
    / "PHASE_4_IMPLEMENTATION.md"
)


def test_profile_request_json_schema_excludes_ownership_and_metadata() -> None:
    schema = FinancialProfilePutRequest.model_json_schema()
    properties = set(schema["properties"])

    assert properties == {
        "income_pattern",
        "income_stability",
        "has_household_responsibilities",
        "dependant_count",
        "emergency_fund_target_months",
    }
    assert set(schema["required"]) == {
        "income_pattern",
        "income_stability",
        "has_household_responsibilities",
        "dependant_count",
    }


def test_profile_response_json_schema_excludes_user_identity() -> None:
    properties = set(
        FinancialProfileResponse.model_json_schema()["properties"]
    )

    assert properties == {
        "id",
        "income_pattern",
        "income_stability",
        "has_household_responsibilities",
        "dependant_count",
        "emergency_fund_target_months",
        "completion_status",
        "created_at",
        "updated_at",
    }
    assert "user_id" not in properties


def test_phase_document_defines_approved_profile_contract() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(
        encoding="utf-8"
    ).lower()

    required_statements = (
        "get /api/v1/profile",
        "put /api/v1/profile",
        "authenticated principal",
        "create-on-first-update",
        "idempotent replacement",
        "profile_not_found",
        "checkpoint 4.1",
        "checkpoint 4.5",
    )

    for statement in required_statements:
        assert statement in content
