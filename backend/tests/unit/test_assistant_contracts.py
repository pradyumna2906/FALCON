"""Phase 12 grounded-answer domain contract tests."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from falcon_api.assistant import (
    ASSISTANT_CONTRACT_VERSION,
    ASSISTANT_SAFETY_POLICY_VERSION,
    AssistantAnswer,
    AssistantAnswerStatus,
    AssistantCitation,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantRefusalReason,
    AssistantReliability,
    AssistantWarning,
)
from falcon_api.assistant.semantics import MAX_CITATIONS, MAX_EVIDENCE_SUMMARIES


def _citation(**changes) -> AssistantCitation:
    values = {
        "source": AssistantEvidenceSource.FORECAST,
        "reference": "forecast:123e4567-e89b-12d3-a456-426614174000",
        "label": "Savings forecast through March 2027",
        "cutoff_at": datetime(2026, 9, 21, 10, tzinfo=UTC),
        "policy_version": "2026.1",
        "reliability": AssistantReliability.NORMAL,
    }
    values.update(changes)
    return AssistantCitation(**values)


def _answer(**changes) -> AssistantAnswer:
    values = {
        "intent": AssistantIntent.EXPLAIN_FORECAST,
        "status": AssistantAnswerStatus.ANSWERED,
        "answer": "Your protected savings forecast remains positive.",
        "evidence_summary": ("Protected monthly savings remains positive.",),
        "citations": (_citation(),),
        "reliability": AssistantReliability.NORMAL,
        "warnings": (AssistantWarning.NOT_FINANCIAL_ADVICE,),
        "suggested_questions": ("How does this affect my goal plan?",),
    }
    values.update(changes)
    return AssistantAnswer(**values)


def test_grounded_answer_is_versioned_cited_and_immutable() -> None:
    answer = _answer()

    assert answer.contract_version == ASSISTANT_CONTRACT_VERSION
    assert answer.safety_policy_version == ASSISTANT_SAFETY_POLICY_VERSION
    assert answer.citations[0].reference.startswith("forecast:")
    with pytest.raises(FrozenInstanceError):
        answer.answer = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"citations": ()}, "cited evidence"),
        ({"evidence_summary": ()}, "cited evidence"),
        (
            {"reliability": AssistantReliability.UNAVAILABLE},
            "available evidence",
        ),
        (
            {"refusal_reason": AssistantRefusalReason.UNSUPPORTED_REQUEST},
            "refusal reason",
        ),
        (
            {"intent": AssistantIntent.UNSUPPORTED},
            "Unsupported intents",
        ),
        (
            {"contract_version": "2099.1"},
            "contract version",
        ),
    ],
)
def test_generated_answer_rejects_ungrounded_or_server_contract_changes(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _answer(**changes)


def test_answer_rejects_duplicate_evidence_and_public_guidance() -> None:
    citation = _citation()
    with pytest.raises(ValueError, match="citations must be unique"):
        _answer(citations=(citation, citation))
    with pytest.raises(ValueError, match="Evidence summary values must be unique"):
        _answer(evidence_summary=("Same", " same "))
    with pytest.raises(ValueError, match="Suggested question values must be unique"):
        _answer(suggested_questions=("Next?", " next? "))
    with pytest.raises(ValueError, match="warnings must be unique"):
        _answer(
            warnings=(
                AssistantWarning.NOT_FINANCIAL_ADVICE,
                AssistantWarning.NOT_FINANCIAL_ADVICE,
            )
        )


def test_answer_enforces_collection_and_safety_policy_bounds() -> None:
    citations = tuple(
        _citation(reference=f"forecast:{index}")
        for index in range(MAX_CITATIONS + 1)
    )
    with pytest.raises(ValueError, match="too many citations"):
        _answer(citations=citations)
    with pytest.raises(ValueError, match="too many values"):
        _answer(
            evidence_summary=tuple(
                f"Evidence {index}" for index in range(MAX_EVIDENCE_SUMMARIES + 1)
            )
        )
    with pytest.raises(ValueError, match="safety policy version"):
        _answer(safety_policy_version="2099.1")
    with pytest.raises(ValueError, match="between 1"):
        _answer(answer="   ")


def test_unavailable_and_refused_dispositions_are_distinct() -> None:
    unavailable = _answer(
        status=AssistantAnswerStatus.UNAVAILABLE,
        answer="There is not enough verified evidence to answer this question.",
        evidence_summary=(),
        citations=(),
        reliability=AssistantReliability.UNAVAILABLE,
        refusal_reason=AssistantRefusalReason.INSUFFICIENT_EVIDENCE,
    )
    refused = _answer(
        intent=AssistantIntent.UNSUPPORTED,
        status=AssistantAnswerStatus.REFUSED,
        answer="This request is outside the assistant's supported scope.",
        evidence_summary=(),
        citations=(),
        reliability=AssistantReliability.UNAVAILABLE,
        refusal_reason=AssistantRefusalReason.UNSUPPORTED_REQUEST,
    )

    assert unavailable.status is AssistantAnswerStatus.UNAVAILABLE
    assert refused.status is AssistantAnswerStatus.REFUSED
    with pytest.raises(ValueError, match="unavailable, not refused"):
        _answer(
            status=AssistantAnswerStatus.REFUSED,
            reliability=AssistantReliability.UNAVAILABLE,
            refusal_reason=AssistantRefusalReason.INSUFFICIENT_EVIDENCE,
        )
    with pytest.raises(ValueError, match="insufficient evidence"):
        _answer(
            status=AssistantAnswerStatus.UNAVAILABLE,
            reliability=AssistantReliability.UNAVAILABLE,
            refusal_reason=AssistantRefusalReason.AUTHORIZATION_REQUIRED,
        )
    with pytest.raises(ValueError, match="unavailable reliability"):
        _answer(
            status=AssistantAnswerStatus.REFUSED,
            reliability=AssistantReliability.NORMAL,
            refusal_reason=AssistantRefusalReason.UNSUPPORTED_REQUEST,
        )
    with pytest.raises(ValueError, match="bounded reason"):
        _answer(
            status=AssistantAnswerStatus.REFUSED,
            reliability=AssistantReliability.UNAVAILABLE,
            refusal_reason=None,
        )
    with pytest.raises(ValueError, match="unsupported-request refusal"):
        _answer(
            intent=AssistantIntent.UNSUPPORTED,
            status=AssistantAnswerStatus.UNAVAILABLE,
            reliability=AssistantReliability.UNAVAILABLE,
            refusal_reason=AssistantRefusalReason.INSUFFICIENT_EVIDENCE,
        )


def test_citation_rejects_unsafe_identity_time_and_unavailable_evidence() -> None:
    with pytest.raises(ValueError, match="unsupported characters"):
        _citation(reference="forecast id with spaces")
    with pytest.raises(ValueError, match="timezone-aware"):
        _citation(cutoff_at=datetime(2026, 9, 21, 10))
    with pytest.raises(ValueError, match="Unavailable evidence"):
        _citation(reliability=AssistantReliability.UNAVAILABLE)
