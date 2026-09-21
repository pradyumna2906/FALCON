"""Phase 12 strict public schema tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from falcon_api.assistant import (
    ASSISTANT_CONTRACT_VERSION,
    AssistantAnswerStatus,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantRefusalReason,
    AssistantReliability,
    AssistantWarning,
)
from falcon_api.schemas.assistant import (
    AssistantAnswerResponse,
    AssistantQuestionRequest,
)


def _response_payload() -> dict[str, object]:
    return {
        "intent": AssistantIntent.EXPLAIN_GOAL_PLAN,
        "status": AssistantAnswerStatus.ANSWERED,
        "answer": "Your protected plan funds the highest-priority goal first.",
        "evidence_summary": ("The protected schedule is fully reconciled.",),
        "citations": (
            {
                "source": AssistantEvidenceSource.GOAL_PLAN,
                "reference": "goal-plan:123e4567-e89b-12d3-a456-426614174000",
                "label": "Approved goal plan",
                "cutoff_at": datetime(2026, 9, 21, 10, tzinfo=UTC),
                "policy_version": "2026.1",
                "reliability": AssistantReliability.NORMAL,
            },
        ),
        "reliability": AssistantReliability.NORMAL,
        "warnings": (AssistantWarning.NOT_FINANCIAL_ADVICE,),
        "suggested_questions": ("How does a lower income affect this plan?",),
    }


def test_question_request_accepts_only_bounded_question_text() -> None:
    assert AssistantQuestionRequest(question="  Explain my forecast.  ").question == (
        "Explain my forecast."
    )
    for forbidden in ("user_id", "model", "cutoff_at", "evidence", "system_prompt"):
        with pytest.raises(ValidationError, match="Extra inputs"):
            AssistantQuestionRequest.model_validate(
                {"question": "Explain my forecast.", forbidden: "blocked"}
            )
    with pytest.raises(ValidationError):
        AssistantQuestionRequest(question="x" * 2_001)


def test_answer_response_round_trips_the_domain_contract() -> None:
    response = AssistantAnswerResponse.model_validate(_response_payload())

    assert response.contract_version == ASSISTANT_CONTRACT_VERSION
    assert response.citations[0].source is AssistantEvidenceSource.GOAL_PLAN
    assert "user_id" not in response.model_dump()


def test_answer_response_rejects_ungrounded_and_private_output_fields() -> None:
    payload = _response_payload()
    payload["citations"] = ()
    with pytest.raises(ValidationError, match="cited evidence"):
        AssistantAnswerResponse.model_validate(payload)

    payload = _response_payload()
    payload["user_id"] = "blocked"
    with pytest.raises(ValidationError, match="Extra inputs"):
        AssistantAnswerResponse.model_validate(payload)


def test_refusal_contract_is_bounded_and_contains_no_private_schema_fields() -> None:
    response = AssistantAnswerResponse(
        intent=AssistantIntent.UNSUPPORTED,
        status=AssistantAnswerStatus.REFUSED,
        answer="This request is outside the assistant's supported scope.",
        evidence_summary=(),
        citations=(),
        reliability=AssistantReliability.UNAVAILABLE,
        refusal_reason=AssistantRefusalReason.UNSUPPORTED_REQUEST,
    )
    schema_text = str(AssistantAnswerResponse.model_json_schema())

    assert response.refusal_reason is AssistantRefusalReason.UNSUPPORTED_REQUEST
    for forbidden in (
        "user_id",
        "raw_prompt",
        "system_prompt",
        "chain_of_thought",
        "account_number",
        "transaction_id",
    ):
        assert forbidden not in schema_text
