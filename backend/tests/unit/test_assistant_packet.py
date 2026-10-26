"""Immutable evidence-packet tests for Phase 12 Checkpoint 12.6."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.assistant import (
    ASSISTANT_PACKET_POLICY_VERSION,
    AssistantEvidencePacket,
    AssistantEvidenceRecord,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantReliability,
    build_evidence_packet,
)


NOW = datetime(2026, 9, 22, 10, tzinfo=UTC)
OWNER_ID = uuid4()


def _record(
    source: AssistantEvidenceSource = AssistantEvidenceSource.FORECAST,
    *,
    reference: str = "forecast-1",
    cutoff_at: datetime = NOW,
    reliability: AssistantReliability = AssistantReliability.NORMAL,
    payload: dict[str, object] | None = None,
) -> AssistantEvidenceRecord:
    return AssistantEvidenceRecord(
        source=source,
        reference=reference,
        label=f"{source.value} evidence",
        cutoff_at=cutoff_at,
        policy_version="2026.1",
        reliability=reliability,
        payload=payload or {},
    )


def _packet(**changes) -> AssistantEvidencePacket:
    values = {
        "question": "What does my savings forecast mean?",
        "intent": AssistantIntent.EXPLAIN_FORECAST,
        "user_id": OWNER_ID,
        "requested_sources": (AssistantEvidenceSource.FORECAST,),
        "evidence": (_record(),),
        "created_at": NOW,
    }
    values.update(changes)
    return build_evidence_packet(**values)


def test_packet_is_deterministic_owner_free_and_deeply_immutable() -> None:
    packet = _packet()
    replay = _packet(question="  What does my savings forecast mean?  ")
    payload = packet.model_payload()

    assert packet.packet_id == replay.packet_id
    assert packet.packet_policy_version == ASSISTANT_PACKET_POLICY_VERSION
    assert packet.can_generate is True
    assert packet.reliability is AssistantReliability.NORMAL
    assert payload["untrusted_user_input"]["question"] == packet.question
    assert "instructions" in payload
    assert "user_id" not in repr(packet)
    assert str(OWNER_ID) not in repr(payload)
    assert payload["evidence"][0]["facts"] == {}
    with pytest.raises(TypeError):
        payload["retrieval"]["reliability"] = "changed"
    with pytest.raises(FrozenInstanceError):
        packet.question = "changed"  # type: ignore[misc]


def test_model_payload_canonicalizes_typed_financial_values() -> None:
    run_id = uuid4()
    record = _record(
        payload={
            "run_id": run_id,
            "cutoff_at": NOW,
            "points": ({"expected_value": Decimal("8500.00")},),
        }
    )

    packet = _packet(evidence=(record,))
    facts = packet.model_payload()["evidence"][0]["facts"]

    assert facts["run_id"] == str(run_id)
    assert facts["cutoff_at"] == NOW.isoformat()
    assert facts["points"][0]["expected_value"] == "8500.00"


def test_packet_build_requires_owner_for_private_sources() -> None:
    with pytest.raises(PermissionError, match="ownership"):
        _packet(user_id=None)


def test_public_knowledge_packet_needs_no_owner() -> None:
    record = _record(
        AssistantEvidenceSource.KNOWLEDGE,
        reference="document:chunk",
        payload={"content": "An emergency fund supports essential expenses."},
    )

    packet = build_evidence_packet(
        question="What is an emergency fund?",
        intent=AssistantIntent.FINANCIAL_EDUCATION,
        user_id=None,
        requested_sources=(AssistantEvidenceSource.KNOWLEDGE,),
        evidence=(record,),
        created_at=NOW,
    )

    assert packet.can_generate is True
    assert packet.citations[record.evidence_id].reference == "document:chunk"


def test_packet_tracks_optional_and_required_missing_sources() -> None:
    optional_missing = _packet(
        requested_sources=(
            AssistantEvidenceSource.FORECAST,
            AssistantEvidenceSource.KNOWLEDGE,
        )
    )
    required_missing = _packet(evidence=())

    assert optional_missing.missing_sources == (
        AssistantEvidenceSource.KNOWLEDGE,
    )
    assert optional_missing.missing_required_sources == ()
    assert optional_missing.can_generate is True
    assert required_missing.missing_required_sources == (
        AssistantEvidenceSource.FORECAST,
    )
    assert required_missing.can_generate is False
    assert required_missing.reliability is AssistantReliability.UNAVAILABLE


def test_packet_requires_intent_defining_source_to_be_requested() -> None:
    knowledge = _record(
        AssistantEvidenceSource.KNOWLEDGE,
        reference="doc:chunk",
        payload={"content": "Forecasts describe uncertain future values."},
    )
    with pytest.raises(ValueError, match="intent-defining"):
        build_evidence_packet(
            question="Explain my forecast",
            intent=AssistantIntent.EXPLAIN_FORECAST,
            user_id=None,
            requested_sources=(AssistantEvidenceSource.KNOWLEDGE,),
            evidence=(knowledge,),
            created_at=NOW,
        )


def test_packet_prefers_latest_record_for_same_resource() -> None:
    older = _record(
        cutoff_at=NOW - timedelta(days=1),
        payload={"points": ({"expected_value": Decimal("7000")},)},
    )
    newest = _record(
        payload={"points": ({"expected_value": Decimal("8500")},)},
    )

    packet = _packet(evidence=(newest, older))

    assert packet.evidence == (newest,)


def test_packet_rejects_conflicting_current_records() -> None:
    first = _record(payload={"points": ({"expected_value": Decimal("7000")},)})
    second = _record(payload={"points": ({"expected_value": Decimal("8500")},)})

    with pytest.raises(ValueError, match="conflicting current"):
        _packet(evidence=(first, second))


def test_packet_rejects_duplicate_future_and_unrequested_evidence() -> None:
    record = _record()
    with pytest.raises(ValueError, match="identities must be unique"):
        _packet(evidence=(record, record))
    with pytest.raises(ValueError, match="future cutoff"):
        _packet(evidence=(_record(cutoff_at=NOW + timedelta(seconds=1)),))
    knowledge = _record(
        AssistantEvidenceSource.KNOWLEDGE,
        reference="doc:chunk",
        payload={"content": "Reviewed education."},
    )
    with pytest.raises(ValueError, match="unrequested"):
        _packet(evidence=(_record(), knowledge))


def test_packet_rejects_incompatible_evidence_policy() -> None:
    record = AssistantEvidenceRecord(
        source=AssistantEvidenceSource.FORECAST,
        reference="forecast-1",
        label="Forecast evidence",
        cutoff_at=NOW,
        policy_version="future",
        reliability=AssistantReliability.NORMAL,
        payload={},
    )

    with pytest.raises(ValueError, match="incompatible policy"):
        _packet(evidence=(record,))


def test_packet_labels_stale_and_worst_reliability() -> None:
    stale = _record(
        cutoff_at=NOW - timedelta(days=121),
        reliability=AssistantReliability.PROVISIONAL,
    )

    packet = _packet(evidence=(stale,))

    assert packet.stale_evidence_ids == (stale.evidence_id,)
    assert packet.reliability is AssistantReliability.PROVISIONAL


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"question": " "}, "question"),
        ({"intent": AssistantIntent.UNSUPPORTED}, "Unsupported"),
        ({"requested_sources": ()}, "sources"),
        ({"input_token_budget": 100}, "input-token"),
        ({"output_token_budget": 100}, "output-token"),
        ({"input_token_budget": 1_024.5}, "input-token"),
        ({"packet_policy_version": "future"}, "policy version"),
        ({"created_at": datetime(2026, 9, 22, 10)}, "timezone-aware"),
    ],
)
def test_packet_rejects_invalid_shape(changes, message) -> None:
    values = {
        "question": "Explain my forecast",
        "intent": AssistantIntent.EXPLAIN_FORECAST,
        "created_at": NOW,
        "requested_sources": (AssistantEvidenceSource.FORECAST,),
        "evidence": (_record(),),
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        AssistantEvidencePacket(**values)


def test_packet_enforces_serialized_context_budget() -> None:
    large = _record(
        payload={"warnings": ("x" * 7_500,)},
    )

    with pytest.raises(ValueError, match="input-token budget"):
        _packet(evidence=(large,), input_token_budget=1_024)
