"""Immutable domain contracts for grounded Phase 12 answers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from falcon_api.assistant.semantics import (
    ASSISTANT_CONTRACT_VERSION,
    ASSISTANT_SAFETY_POLICY_VERSION,
    MAX_ANSWER_CHARACTERS,
    MAX_CITATION_LABEL_CHARACTERS,
    MAX_CITATIONS,
    MAX_EVIDENCE_SUMMARIES,
    MAX_EVIDENCE_SUMMARY_CHARACTERS,
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


_SOURCE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _text(value: str, *, label: str, maximum: int) -> str:
    resolved = value.strip()
    if not resolved or len(resolved) > maximum:
        raise ValueError(f"{label} must contain between 1 and {maximum} characters.")
    return resolved


def _unique_texts(
    values: tuple[str, ...],
    *,
    label: str,
    maximum_items: int,
    maximum_characters: int,
) -> tuple[str, ...]:
    if len(values) > maximum_items:
        raise ValueError(f"{label} contains too many values.")
    resolved = tuple(
        _text(item, label=label, maximum=maximum_characters) for item in values
    )
    if len({item.casefold() for item in resolved}) != len(resolved):
        raise ValueError(f"{label} values must be unique.")
    return resolved


@dataclass(frozen=True, slots=True)
class AssistantCitation:
    """One owner-safe reference supporting a material assistant claim."""

    source: AssistantEvidenceSource
    reference: str
    label: str
    cutoff_at: datetime
    policy_version: str
    reliability: AssistantReliability

    def __post_init__(self) -> None:
        reference = _text(
            self.reference,
            label="Citation reference",
            maximum=MAX_SOURCE_REFERENCE_CHARACTERS,
        )
        if _SOURCE_REFERENCE_PATTERN.fullmatch(reference) is None:
            raise ValueError("Citation reference contains unsupported characters.")
        if self.cutoff_at.tzinfo is None or self.cutoff_at.utcoffset() is None:
            raise ValueError("Citation cutoff must be timezone-aware.")
        if self.reliability is AssistantReliability.UNAVAILABLE:
            raise ValueError("Unavailable evidence cannot be cited.")
        object.__setattr__(self, "reference", reference)
        object.__setattr__(
            self,
            "label",
            _text(
                self.label,
                label="Citation label",
                maximum=MAX_CITATION_LABEL_CHARACTERS,
            ),
        )
        object.__setattr__(
            self,
            "policy_version",
            _text(self.policy_version, label="Policy version", maximum=32),
        )


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    """Complete public answer contract before transport serialization."""

    intent: AssistantIntent
    status: AssistantAnswerStatus
    answer: str
    evidence_summary: tuple[str, ...]
    citations: tuple[AssistantCitation, ...]
    reliability: AssistantReliability
    warnings: tuple[AssistantWarning, ...] = ()
    suggested_questions: tuple[str, ...] = ()
    refusal_reason: AssistantRefusalReason | None = None
    contract_version: str = ASSISTANT_CONTRACT_VERSION
    safety_policy_version: str = ASSISTANT_SAFETY_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "answer",
            _text(
                self.answer,
                label="Assistant answer",
                maximum=MAX_ANSWER_CHARACTERS,
            ),
        )
        object.__setattr__(
            self,
            "evidence_summary",
            _unique_texts(
                self.evidence_summary,
                label="Evidence summary",
                maximum_items=MAX_EVIDENCE_SUMMARIES,
                maximum_characters=MAX_EVIDENCE_SUMMARY_CHARACTERS,
            ),
        )
        object.__setattr__(
            self,
            "suggested_questions",
            _unique_texts(
                self.suggested_questions,
                label="Suggested question",
                maximum_items=MAX_SUGGESTED_QUESTIONS,
                maximum_characters=MAX_SUGGESTED_QUESTION_CHARACTERS,
            ),
        )
        if len(self.citations) > MAX_CITATIONS:
            raise ValueError("Assistant answer contains too many citations.")
        citation_keys = {(item.source, item.reference) for item in self.citations}
        if len(citation_keys) != len(self.citations):
            raise ValueError("Assistant citations must be unique.")
        if len(set(self.warnings)) != len(self.warnings):
            raise ValueError("Assistant warnings must be unique.")
        if self.contract_version != ASSISTANT_CONTRACT_VERSION:
            raise ValueError("Assistant contract version is unsupported.")
        if self.safety_policy_version != ASSISTANT_SAFETY_POLICY_VERSION:
            raise ValueError("Assistant safety policy version is unsupported.")
        self._validate_disposition()

    def _validate_disposition(self) -> None:
        generated = self.status in {
            AssistantAnswerStatus.ANSWERED,
            AssistantAnswerStatus.LIMITED,
        }
        if generated:
            if self.intent is AssistantIntent.UNSUPPORTED:
                raise ValueError("Unsupported intents cannot produce an answer.")
            if self.refusal_reason is not None:
                raise ValueError("Generated answers cannot include a refusal reason.")
            if not self.citations or not self.evidence_summary:
                raise ValueError("Generated answers require cited evidence.")
            if self.reliability is AssistantReliability.UNAVAILABLE:
                raise ValueError("Generated answers require available evidence.")
            return

        if self.reliability is not AssistantReliability.UNAVAILABLE:
            raise ValueError("Unavailable or refused answers require unavailable reliability.")
        if self.refusal_reason is None:
            raise ValueError("Unavailable or refused answers require a bounded reason.")
        if self.status is AssistantAnswerStatus.UNAVAILABLE:
            if self.refusal_reason is not AssistantRefusalReason.INSUFFICIENT_EVIDENCE:
                raise ValueError("Unavailable answers require insufficient evidence.")
        elif self.status is AssistantAnswerStatus.REFUSED:
            if self.refusal_reason is AssistantRefusalReason.INSUFFICIENT_EVIDENCE:
                raise ValueError("Insufficient evidence is unavailable, not refused.")
        if self.intent is AssistantIntent.UNSUPPORTED and (
            self.status is not AssistantAnswerStatus.REFUSED
            or self.refusal_reason is not AssistantRefusalReason.UNSUPPORTED_REQUEST
        ):
            raise ValueError("Unsupported intent requires an unsupported-request refusal.")
