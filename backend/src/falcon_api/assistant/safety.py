"""Deterministic safety screening before retrieval, generation, and release."""

from __future__ import annotations

import re
from collections.abc import Iterable

from falcon_api.assistant.contracts import AssistantAnswer
from falcon_api.assistant.packet import AssistantEvidencePacket
from falcon_api.assistant.semantics import (
    AssistantAnswerStatus,
    AssistantIntent,
    AssistantRefusalReason,
    AssistantReliability,
    AssistantWarning,
)


_ATTACKS: tuple[tuple[AssistantRefusalReason, re.Pattern[str]], ...] = (
    (AssistantRefusalReason.PROMPT_INJECTION, re.compile(
        r"\b(?:ignore|override|discard|forget)\s+(?:all\s+|previous\s+|prior\s+|your\s+|the\s+)*"
        r"(?:instructions|rules|system prompt|policy|safety checks)\b|"
        r"\b(?:reveal|print|show|repeat)\s+(?:your\s+|the\s+)*(?:system prompt|hidden instructions|chain.of.thought)\b|"
        r"\b(?:you are now|act as (?:the )?system|developer message:|system message:|disable (?:the )?safety)\b",
        re.IGNORECASE,
    )),
    (AssistantRefusalReason.DATA_EXFILTRATION, re.compile(
        r"\b(?:show|give|export|send|list|reveal)\s+(?:me\s+)?(?:all\s+)?"
        r"(?:other users?'?|someone else's|another user's)\s+(?:data|transactions|accounts|balances|details)\b|"
        r"\b(?:send|post|upload)\s+(?:the\s+)?(?:user\s+)?(?:data|evidence|records|secrets)\s+to\s+https?://|"
        r"\b(?:expose|reveal|show)\s+(?:the\s+)?(?:password|api key|access token|private key)\b",
        re.IGNORECASE,
    )),
    (AssistantRefusalReason.PROHIBITED_FINANCIAL_ACTION, re.compile(
        r"\b(?:transfer|send|move|withdraw)\s+(?:my\s+|the\s+)?(?:money|funds|balance)\b|"
        r"\b(?:create|delete|change|edit|approve)\s+(?:my\s+|the\s+)?"
        r"(?:transaction|account|goal plan|contribution|payment)\b",
        re.IGNORECASE,
    )),
    (AssistantRefusalReason.PRODUCT_SPECIFIC_INVESTMENT_ADVICE, re.compile(
        r"\b(?:should i|tell me to|recommend|which)\s+(?:buy|sell|invest in)\s+"
        r"(?:a\s+|the\s+)?(?:stock|share|crypto|bitcoin|mutual fund|security|etf)\b|"
        r"\b(?:buy|sell)\s+(?:a\s+|the\s+)?(?:stock|share|crypto|bitcoin|security)\b",
        re.IGNORECASE,
    )),
    (AssistantRefusalReason.GUARANTEED_OUTCOME, re.compile(
        r"\b(?:guarantee|promise|ensure)\s+(?:me\s+|that\s+)?(?:a\s+)?"
        r"(?:profit|return|goal|outcome|result|success)\b|\b(?:risk.free|certain profit)\b",
        re.IGNORECASE,
    )),
)

_RETRIEVED_INSTRUCTIONS = re.compile(
    r"\b(?:ignore|override|discard)\s+(?:all\s+|previous\s+|prior\s+|your\s+|the\s+)*"
    r"(?:instructions|rules|policy|system prompt)\b|"
    r"\b(?:system|developer)\s*(?:message|instruction|prompt)\s*:|"
    r"\b(?:send|post|upload)\s+(?:user\s+)?(?:data|evidence|secrets)\s+to\s+https?://|"
    r"\b(?:reveal|print)\s+(?:the\s+|your\s+)?(?:system prompt|secret|chain.of.thought)\b",
    re.IGNORECASE,
)
_PRIVATE_OUTPUT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\b(?:password|api key|access token|refresh token|private key)\s*[:=]\s*\S+|"
    r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)",
    re.IGNORECASE,
)


def screen_question(question: str, *, intent: AssistantIntent) -> AssistantAnswer | None:
    """Run before retrieval; no model or database is needed to refuse abuse."""

    if intent is AssistantIntent.UNSUPPORTED:
        return refusal(intent, AssistantRefusalReason.UNSUPPORTED_REQUEST)
    for reason, pattern in _ATTACKS:
        if pattern.search(question):
            return refusal(intent, reason)
    return None


def screen_packet(packet: AssistantEvidencePacket) -> AssistantAnswer | None:
    """Treat all retrieved facts as inert data and fail closed on instructions."""

    denied = screen_question(packet.question, intent=packet.intent)
    if denied:
        return denied
    for record in packet.evidence:
        if _RETRIEVED_INSTRUCTIONS.search(record.label) or any(
            _RETRIEVED_INSTRUCTIONS.search(value) for value in _strings(record.payload)
        ):
            return refusal(packet.intent, AssistantRefusalReason.PROMPT_INJECTION)
    return None


def screen_public_text(text: str) -> None:
    """Reject accidental credential, identity, account, or instruction leakage."""

    if _PRIVATE_OUTPUT.search(text) or _RETRIEVED_INSTRUCTIONS.search(text):
        raise ValueError("Assistant output contains unsafe private or instructional text.")


def refusal(intent: AssistantIntent, reason: AssistantRefusalReason) -> AssistantAnswer:
    messages = {
        AssistantRefusalReason.UNSUPPORTED_REQUEST: "I can only explain supported FALCON financial evidence and curated education.",
        AssistantRefusalReason.PROMPT_INJECTION: "I cannot follow instructions that change the assistant's safety or evidence rules.",
        AssistantRefusalReason.DATA_EXFILTRATION: "I cannot disclose private data, credentials, or another person's records.",
        AssistantRefusalReason.PROHIBITED_FINANCIAL_ACTION: "I cannot perform financial actions or change your financial records.",
        AssistantRefusalReason.PRODUCT_SPECIFIC_INVESTMENT_ADVICE: "I cannot recommend buying or selling a particular investment product.",
        AssistantRefusalReason.GUARANTEED_OUTCOME: "I cannot promise a financial outcome or risk-free result.",
    }
    return AssistantAnswer(
        intent=intent,
        status=AssistantAnswerStatus.REFUSED,
        answer=messages[reason],
        evidence_summary=(),
        citations=(),
        reliability=AssistantReliability.UNAVAILABLE,
        warnings=(AssistantWarning.NOT_FINANCIAL_ADVICE,),
        refusal_reason=reason,
    )


def _strings(value: object) -> Iterable[str]:
    from collections.abc import Mapping, Sequence

    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _strings(item)


__all__ = ["refusal", "screen_packet", "screen_public_text", "screen_question"]
