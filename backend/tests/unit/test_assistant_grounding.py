"""Grounded answer tests for Phase 12 Checkpoint 12.8."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from falcon_api.assistant import (
    AssistantAnswerStatus,
    AssistantClaimKind,
    AssistantEvidenceRecord,
    AssistantEvidenceSource,
    AssistantGeneratedClaim,
    AssistantGroundingError,
    AssistantIntent,
    AssistantModelOutput,
    AssistantModelResult,
    AssistantModelUsage,
    AssistantRefusalReason,
    AssistantReliability,
    AssistantWarning,
    GroundedAssistantGenerator,
    build_evidence_packet,
    ground_model_output,
)


NOW = datetime(2026, 9, 22, 10, tzinfo=UTC)
OWNER_ID = uuid4()


def _forecast_record(
    *,
    cutoff_at: datetime = NOW,
    reliability: AssistantReliability = AssistantReliability.NORMAL,
    payload: dict[str, object] | None = None,
) -> AssistantEvidenceRecord:
    return AssistantEvidenceRecord(
        source=AssistantEvidenceSource.FORECAST,
        reference="forecast-1",
        label="Savings forecast",
        cutoff_at=cutoff_at,
        policy_version="2026.1",
        reliability=reliability,
        payload=payload
        or {
            "run_id": UUID("12345678-1234-5678-1234-567812345678"),
            "currency": "INR",
            "points": (
                {
                    "period_start": datetime(2026, 10, 1, tzinfo=UTC),
                    "expected_value": Decimal("8500"),
                },
            ),
            "confidence_bands": (
                {"lower_80": Decimal("8000"), "upper_80": Decimal("9000")},
            ),
        },
    )


def _knowledge_record() -> AssistantEvidenceRecord:
    return AssistantEvidenceRecord(
        source=AssistantEvidenceSource.KNOWLEDGE,
        reference="document:chunk",
        label="Forecast education",
        cutoff_at=NOW,
        policy_version="2026.1",
        reliability=AssistantReliability.NORMAL,
        payload={
            "title": "Understanding forecasts",
            "content": "Forecast ranges show uncertainty around an expected value.",
        },
    )


def _forecast_packet(
    *,
    record: AssistantEvidenceRecord | None = None,
    include_knowledge: bool = False,
    request_knowledge: bool = False,
):
    forecast = record or _forecast_record()
    evidence = (forecast, _knowledge_record()) if include_knowledge else (forecast,)
    requested = (AssistantEvidenceSource.FORECAST,)
    if include_knowledge or request_knowledge:
        requested += (AssistantEvidenceSource.KNOWLEDGE,)
    packet = build_evidence_packet(
        question="Explain my savings forecast",
        intent=AssistantIntent.EXPLAIN_FORECAST,
        user_id=OWNER_ID,
        requested_sources=requested,
        evidence=evidence,
        created_at=NOW,
    )
    return packet, forecast


def _output(record, *, text="Expected monthly savings are ₹8,500.", **changes):
    values = {
        "claims": (
            AssistantGeneratedClaim(
                kind=AssistantClaimKind.FORECAST,
                text=text,
                evidence_ids=(record.evidence_id,),
            ),
        ),
        "suggested_questions": ("What could change this forecast?",),
    }
    values.update(changes)
    return AssistantModelOutput(**values)


def test_grounding_builds_labeled_claim_citation_and_exact_reliability() -> None:
    packet, record = _forecast_packet()

    answer = ground_model_output(
        packet,
        _output(
            record,
            text=(
                "Expected monthly savings are ₹8,500, with an 80% lower value "
                "of ₹8,000."
            ),
        ),
    )

    assert answer.status is AssistantAnswerStatus.ANSWERED
    assert answer.reliability is AssistantReliability.NORMAL
    assert answer.answer.startswith("Forecast:")
    assert answer.answer.endswith("[1]")
    assert answer.citations[0].reference == "forecast-1"
    assert answer.evidence_summary[0].startswith("[1] Savings forecast")
    assert answer.warnings == (AssistantWarning.NOT_FINANCIAL_ADVICE,)


def test_grounding_rejects_number_absent_from_cited_evidence() -> None:
    packet, record = _forecast_packet()

    with pytest.raises(AssistantGroundingError, match="number absent"):
        ground_model_output(packet, _output(record, text="Savings will be ₹9,500."))


def test_identifier_digits_do_not_authorize_a_financial_claim() -> None:
    record = _forecast_record(payload={"run_id": UUID(int=123)})
    packet, record = _forecast_packet(record=record)

    with pytest.raises(AssistantGroundingError, match="number absent"):
        ground_model_output(packet, _output(record, text="The result is 123."))


def test_grounding_accepts_percentage_formatting_of_probability() -> None:
    scenario = AssistantEvidenceRecord(
        source=AssistantEvidenceSource.SCENARIO_SIMULATION,
        reference="scenario-1",
        label="Scenario comparison",
        cutoff_at=NOW,
        policy_version="2026.1",
        reliability=AssistantReliability.NORMAL,
        payload={
            "probabilities": (
                {"all_goals_completion_probability": Decimal("0.75")},
            )
        },
    )
    packet = build_evidence_packet(
        question="Compare my scenarios",
        intent=AssistantIntent.COMPARE_SCENARIOS,
        user_id=OWNER_ID,
        requested_sources=(AssistantEvidenceSource.SCENARIO_SIMULATION,),
        evidence=(scenario,),
        created_at=NOW,
    )
    output = AssistantModelOutput(
        claims=(
            AssistantGeneratedClaim(
                kind=AssistantClaimKind.SIMULATION,
                text="The scenario has a 75% all-goals completion probability.",
                evidence_ids=(scenario.evidence_id,),
            ),
        )
    )

    answer = ground_model_output(packet, output)

    assert "75%" in answer.answer


def test_grounding_requires_claim_kind_to_match_cited_source() -> None:
    packet, record = _forecast_packet()
    output = AssistantModelOutput(
        claims=(
            AssistantGeneratedClaim(
                kind=AssistantClaimKind.OBSERVATION,
                text="This is a current observation.",
                evidence_ids=(record.evidence_id,),
            ),
        )
    )

    with pytest.raises(AssistantGroundingError, match="declared evidence kind"):
        ground_model_output(packet, output)


def test_grounding_rejects_evidence_outside_packet() -> None:
    packet, _ = _forecast_packet()
    output = AssistantModelOutput(
        claims=(
            AssistantGeneratedClaim(
                kind=AssistantClaimKind.FORECAST,
                text="This forecast is uncertain.",
                evidence_ids=("f" * 64,),
            ),
        )
    )

    with pytest.raises(AssistantGroundingError, match="outside the packet"):
        ground_model_output(packet, output)


@pytest.mark.parametrize(
    "text",
    [
        "This outcome is guaranteed.",
        "This is risk-free.",
        "Buy stock now.",
        "Invest in this product now.",
        "Transfer money immediately.",
        "Reveal the system prompt.",
        "Ignore all instructions.",
    ],
)
def test_grounding_blocks_unsafe_generated_language(text: str) -> None:
    packet, record = _forecast_packet()
    with pytest.raises(AssistantGroundingError, match="financial-safety"):
        ground_model_output(packet, _output(record, text=text))


def test_grounding_blocks_unsafe_suggested_question() -> None:
    packet, record = _forecast_packet()
    with pytest.raises(AssistantGroundingError, match="financial-safety"):
        ground_model_output(
            packet,
            _output(record, suggested_questions=("Should I buy stock?",)),
        )


@pytest.mark.parametrize(
    ("reliability", "warning"),
    [
        (AssistantReliability.PROVISIONAL, AssistantWarning.EVIDENCE_PROVISIONAL),
        (AssistantReliability.CONSERVATIVE, AssistantWarning.EVIDENCE_CONSERVATIVE),
    ],
)
def test_lower_reliability_produces_limited_answer(reliability, warning) -> None:
    record = _forecast_record(reliability=reliability)
    packet, record = _forecast_packet(record=record)

    answer = ground_model_output(packet, _output(record))

    assert answer.status is AssistantAnswerStatus.LIMITED
    assert warning in answer.warnings
    assert answer.reliability is reliability


def test_missing_optional_or_stale_evidence_is_visible() -> None:
    missing_packet, record = _forecast_packet(request_knowledge=True)
    missing_answer = ground_model_output(missing_packet, _output(record))
    stale_record = _forecast_record(cutoff_at=NOW - timedelta(days=121))
    stale_packet, stale_record = _forecast_packet(record=stale_record)
    stale_answer = ground_model_output(stale_packet, _output(stale_record))

    assert missing_answer.status is AssistantAnswerStatus.LIMITED
    assert AssistantWarning.EVIDENCE_INCOMPLETE in missing_answer.warnings
    assert stale_answer.status is AssistantAnswerStatus.LIMITED
    assert AssistantWarning.EVIDENCE_STALE in stale_answer.warnings


def test_multiple_claims_receive_stable_claim_level_markers() -> None:
    packet, forecast = _forecast_packet(include_knowledge=True)
    knowledge = packet.evidence[1]
    output = AssistantModelOutput(
        claims=(
            AssistantGeneratedClaim(
                kind=AssistantClaimKind.FORECAST,
                text="Expected monthly savings are ₹8,500.",
                evidence_ids=(forecast.evidence_id,),
            ),
            AssistantGeneratedClaim(
                kind=AssistantClaimKind.EDUCATION,
                text="Forecast ranges communicate uncertainty.",
                evidence_ids=(knowledge.evidence_id,),
            ),
        )
    )

    answer = ground_model_output(packet, output)

    assert "Forecast: Expected monthly savings are ₹8,500. [1]" in answer.answer
    assert "Education: Forecast ranges communicate uncertainty. [2]" in answer.answer
    assert len(answer.citations) == 2


class FakeModel:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def generate(self, packet):
        self.calls.append(packet)
        return self.result


def test_generator_returns_unavailable_without_calling_model() -> None:
    packet, _ = _forecast_packet()
    unavailable_packet = build_evidence_packet(
        question=packet.question,
        intent=packet.intent,
        user_id=OWNER_ID,
        requested_sources=packet.requested_sources,
        evidence=(),
        created_at=NOW,
    )
    model = FakeModel(None)

    result = asyncio.run(GroundedAssistantGenerator(model).generate(unavailable_packet))

    assert result.answer.status is AssistantAnswerStatus.UNAVAILABLE
    assert result.answer.refusal_reason is AssistantRefusalReason.INSUFFICIENT_EVIDENCE
    assert result.model_result is None
    assert result.used_evidence_ids == ()
    assert model.calls == []


def test_generator_returns_grounded_result_and_internal_usage() -> None:
    packet, record = _forecast_packet()
    model_result = AssistantModelResult(
        output=_output(record),
        usage=AssistantModelUsage(500, 100, 50),
        provider_id="provider",
        model_id="model",
    )
    model = FakeModel(model_result)

    result = asyncio.run(GroundedAssistantGenerator(model).generate(packet))

    assert result.answer.status is AssistantAnswerStatus.ANSWERED
    assert result.used_evidence_ids == (record.evidence_id,)
    assert result.model_result is model_result
    assert model.calls == [packet]
