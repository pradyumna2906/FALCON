"""Strict public schemas reserved for the grounded Phase 12 assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from falcon_api.assistant.contracts import AssistantAnswer, AssistantCitation
from falcon_api.assistant.semantics import (
    ASSISTANT_CONTRACT_VERSION,
    ASSISTANT_SAFETY_POLICY_VERSION,
    MAX_ANSWER_CHARACTERS,
    MAX_CITATION_LABEL_CHARACTERS,
    MAX_CITATIONS,
    MAX_EVIDENCE_SUMMARIES,
    MAX_EVIDENCE_SUMMARY_CHARACTERS,
    MAX_QUESTION_CHARACTERS,
    MAX_SOURCE_REFERENCE_CHARACTERS,
    MAX_SUGGESTED_QUESTION_CHARACTERS,
    MAX_SUGGESTED_QUESTIONS,
    AssistantAnswerStatus,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantRefusalReason,
    AssistantReliability,
    AssistantWarning,
)


QuestionText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_QUESTION_CHARACTERS,
    ),
]
AnswerText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ANSWER_CHARACTERS),
]
SummaryText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_EVIDENCE_SUMMARY_CHARACTERS,
    ),
]
SuggestedQuestion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_SUGGESTED_QUESTION_CHARACTERS,
    ),
]


class AssistantSchema(BaseModel):
    """Reject server-owned or unknown fields at the public boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class AssistantQuestionRequest(AssistantSchema):
    """The only client-controlled input in the initial answer contract."""

    question: QuestionText


class AssistantCitationResponse(AssistantSchema):
    source: AssistantEvidenceSource
    reference: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_SOURCE_REFERENCE_CHARACTERS,
        ),
    ]
    label: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_CITATION_LABEL_CHARACTERS,
        ),
    ]
    cutoff_at: datetime
    policy_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
    ]
    reliability: AssistantReliability

    @model_validator(mode="after")
    def validate_domain_contract(self) -> AssistantCitationResponse:
        AssistantCitation(**self.model_dump())
        return self


class AssistantAnswerResponse(AssistantSchema):
    intent: AssistantIntent
    status: AssistantAnswerStatus
    answer: AnswerText
    evidence_summary: Annotated[
        tuple[SummaryText, ...],
        Field(max_length=MAX_EVIDENCE_SUMMARIES),
    ]
    citations: Annotated[
        tuple[AssistantCitationResponse, ...],
        Field(max_length=MAX_CITATIONS),
    ]
    reliability: AssistantReliability
    warnings: tuple[AssistantWarning, ...] = ()
    suggested_questions: Annotated[
        tuple[SuggestedQuestion, ...],
        Field(max_length=MAX_SUGGESTED_QUESTIONS),
    ] = ()
    refusal_reason: AssistantRefusalReason | None = None
    contract_version: str = ASSISTANT_CONTRACT_VERSION
    safety_policy_version: str = ASSISTANT_SAFETY_POLICY_VERSION

    @model_validator(mode="after")
    def validate_domain_contract(self) -> AssistantAnswerResponse:
        AssistantAnswer(
            intent=self.intent,
            status=self.status,
            answer=self.answer,
            evidence_summary=self.evidence_summary,
            citations=tuple(
                AssistantCitation(**item.model_dump()) for item in self.citations
            ),
            reliability=self.reliability,
            warnings=self.warnings,
            suggested_questions=self.suggested_questions,
            refusal_reason=self.refusal_reason,
            contract_version=self.contract_version,
            safety_policy_version=self.safety_policy_version,
        )
        return self


class AssistantConversationResponse(AssistantSchema):
    """Owner-visible metadata without encrypted content or internal provenance."""

    id: UUID
    created_at: datetime
    expires_at: datetime
    turn_count: Annotated[int, Field(ge=0, le=50)]


class AssistantConversationListResponse(AssistantSchema):
    items: Annotated[
        tuple[AssistantConversationResponse, ...],
        Field(max_length=20),
    ]


class AssistantMessageResponse(AssistantSchema):
    """One decrypted owner-visible exchange and its verified public answer."""

    id: UUID
    conversation_id: UUID
    ordinal: Annotated[int, Field(ge=1, le=50)]
    question: QuestionText
    answer: AssistantAnswerResponse
    created_at: datetime
    replayed: bool = False


class AssistantConversationDetailResponse(AssistantConversationResponse):
    messages: Annotated[
        tuple[AssistantMessageResponse, ...],
        Field(max_length=20),
    ]
    has_more: bool


class AssistantCitationListResponse(AssistantSchema):
    message_id: UUID
    items: Annotated[
        tuple[AssistantCitationResponse, ...],
        Field(max_length=MAX_CITATIONS),
    ]
