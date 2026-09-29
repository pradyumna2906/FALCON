"""Phase 12 evidence authorization, prompt privacy, and threat-model tests."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

import pytest

from falcon_api.assistant import (
    ASSISTANT_PRIVACY_POLICY_VERSION,
    ASSISTANT_THREAT_MODEL,
    FORBIDDEN_PROMPT_FIELDS,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantThreat,
    authorize_evidence_sources,
    privacy_policy_version,
    prompt_safe_payload,
    source_policy,
)


def test_source_registry_is_closed_owner_aware_and_excludes_raw_finance() -> None:
    assert privacy_policy_version() == ASSISTANT_PRIVACY_POLICY_VERSION
    assert {source_policy(source).source for source in AssistantEvidenceSource} == set(
        AssistantEvidenceSource
    )
    for source in AssistantEvidenceSource:
        policy = source_policy(source)
        assert policy.allowed_fields
        assert not policy.allowed_fields & FORBIDDEN_PROMPT_FIELDS
        assert policy.requires_owner is (
            source is not AssistantEvidenceSource.KNOWLEDGE
        )
    assert "transaction" not in {item.value for item in AssistantEvidenceSource}
    assert "account" not in {item.value for item in AssistantEvidenceSource}


def test_source_authorization_uses_intent_and_authenticated_owner() -> None:
    owner_id = uuid4()
    policies = authorize_evidence_sources(
        intent=AssistantIntent.EXPLAIN_FORECAST,
        sources=(
            AssistantEvidenceSource.FORECAST,
            AssistantEvidenceSource.KNOWLEDGE,
        ),
        user_id=owner_id,
    )
    assert [item.source for item in policies] == [
        AssistantEvidenceSource.FORECAST,
        AssistantEvidenceSource.KNOWLEDGE,
    ]
    assert authorize_evidence_sources(
        intent=AssistantIntent.FINANCIAL_EDUCATION,
        sources=(AssistantEvidenceSource.KNOWLEDGE,),
        user_id=None,
    )
    with pytest.raises(PermissionError, match="ownership"):
        authorize_evidence_sources(
            intent=AssistantIntent.EXPLAIN_FORECAST,
            sources=(AssistantEvidenceSource.FORECAST,),
            user_id=None,
        )
    with pytest.raises(PermissionError, match="not allowed"):
        authorize_evidence_sources(
            intent=AssistantIntent.FINANCIAL_EDUCATION,
            sources=(AssistantEvidenceSource.SCENARIO_SIMULATION,),
            user_id=owner_id,
        )
    with pytest.raises(ValueError, match="unique"):
        authorize_evidence_sources(
            intent=AssistantIntent.FINANCIAL_EDUCATION,
            sources=(
                AssistantEvidenceSource.KNOWLEDGE,
                AssistantEvidenceSource.KNOWLEDGE,
            ),
            user_id=None,
        )


def test_prompt_payload_accepts_only_allowlisted_bounded_values() -> None:
    payload = prompt_safe_payload(
        AssistantEvidenceSource.FORECAST,
        {
            "run_id": uuid4(),
            "cutoff_at": datetime(2026, 9, 21, 10, tzinfo=UTC),
            "currency": "INR",
            "points": (
                {
                    "period": "2026-10",
                    "expected": Decimal("1000.0000"),
                },
            ),
            "reliability": "normal",
        },
    )

    assert payload["currency"] == "INR"
    assert isinstance(payload["points"], tuple)
    with pytest.raises(ValueError, match="outside its allowlist"):
        prompt_safe_payload(
            AssistantEvidenceSource.FORECAST,
            {"user_id": uuid4()},
        )
    with pytest.raises(ValueError, match="forbidden private field"):
        prompt_safe_payload(
            AssistantEvidenceSource.FORECAST,
            {"points": ({"transaction_id": str(uuid4())},)},
        )
    with pytest.raises(ValueError, match="non-finite"):
        prompt_safe_payload(
            AssistantEvidenceSource.FORECAST,
            {"quality": float("nan")},
        )
    with pytest.raises(ValueError, match="unsupported value type"):
        prompt_safe_payload(
            AssistantEvidenceSource.FORECAST,
            {"quality": b"private"},
        )


def test_prompt_payload_enforces_text_collection_and_depth_bounds() -> None:
    with pytest.raises(ValueError, match="text exceeds"):
        prompt_safe_payload(
            AssistantEvidenceSource.KNOWLEDGE,
            {"content": "x" * 8_001},
        )
    with pytest.raises(ValueError, match="collection limit"):
        prompt_safe_payload(
            AssistantEvidenceSource.KNOWLEDGE,
            {"content": tuple(range(501))},
        )
    with pytest.raises(ValueError, match="mapping exceeds"):
        prompt_safe_payload(
            AssistantEvidenceSource.KNOWLEDGE,
            {"content": {str(index): index for index in range(501)}},
        )
    with pytest.raises(ValueError, match="keys must be strings"):
        prompt_safe_payload(
            AssistantEvidenceSource.KNOWLEDGE,
            {"content": {1: "blocked"}},
        )
    deeply_nested: object = "safe"
    for _ in range(7):
        deeply_nested = {"level": deeply_nested}
    with pytest.raises(ValueError, match="nesting limit"):
        prompt_safe_payload(
            AssistantEvidenceSource.KNOWLEDGE,
            {"content": deeply_nested},
        )


def test_prompt_payload_preserves_finite_numbers_and_serializes_plain_enums() -> None:
    class Reliability(Enum):
        NORMAL = "normal"

    payload = prompt_safe_payload(
        AssistantEvidenceSource.FORECAST,
        {"quality": {"score": 0.95, "state": Reliability.NORMAL}},
    )

    assert payload == {"quality": {"score": 0.95, "state": "normal"}}


def test_threat_model_covers_every_reserved_threat_once() -> None:
    assert {item.threat for item in ASSISTANT_THREAT_MODEL} == set(AssistantThreat)
    assert len(ASSISTANT_THREAT_MODEL) == len(AssistantThreat)
    assert all(item.control.strip() and item.verification.strip() for item in ASSISTANT_THREAT_MODEL)
