"""Privacy-safe low-cardinality telemetry for grounded assistant requests."""

from __future__ import annotations

import logging
from enum import StrEnum

from falcon_api.assistant.semantics import (
    ASSISTANT_GENERATION_POLICY_VERSION,
    MAX_CITATIONS,
    MAX_EVIDENCE_RECORDS,
    MAX_EVIDENCE_REQUESTS,
    MAX_MODEL_OUTPUT_TOKENS,
    MAX_PACKET_INPUT_TOKENS,
    AssistantAnswerStatus,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantRefusalReason,
)


class AssistantProviderOutcome(StrEnum):
    """Closed provider states that disclose no transport configuration."""

    NOT_CALLED = "not_called"
    SUCCEEDED = "succeeded"
    REPLAYED = "replayed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    MALFORMED = "malformed"
    OVER_BUDGET = "over_budget"
    VERIFICATION_BLOCKED = "verification_blocked"


class AssistantFailureReason(StrEnum):
    """Safe operational failure categories without request or identity data."""

    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    CONCURRENCY_LIMITED = "concurrency_limited"
    HISTORY_LIMIT = "history_limit"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    REQUEST_TIMEOUT = "request_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_INVALID = "provider_invalid"


class AssistantMonitor:
    """Emit aggregate request outcomes without prompts, owners, or amounts."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("falcon_api.assistant")

    def record_completion(
        self,
        *,
        intent: AssistantIntent,
        sources: tuple[AssistantEvidenceSource, ...],
        evidence_count: int,
        status: AssistantAnswerStatus,
        refusal_reason: AssistantRefusalReason | None,
        citation_count: int,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        provider_outcome: AssistantProviderOutcome,
    ) -> None:
        """Validate and record one completed, persisted or replayed response."""

        _validate_counts(
            sources=sources,
            evidence_count=evidence_count,
            citation_count=citation_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        if status is AssistantAnswerStatus.REFUSED:
            if refusal_reason in {None, AssistantRefusalReason.INSUFFICIENT_EVIDENCE}:
                raise ValueError("Refusal telemetry requires a closed policy reason.")
        elif status is AssistantAnswerStatus.UNAVAILABLE:
            if refusal_reason is not AssistantRefusalReason.INSUFFICIENT_EVIDENCE:
                raise ValueError("Unavailable telemetry requires insufficient evidence.")
        elif refusal_reason is not None:
            raise ValueError("Generated-answer telemetry cannot contain a refusal.")
        self._logger.info(
            "assistant_request_completed",
            extra={
                "assistant_policy_version": ASSISTANT_GENERATION_POLICY_VERSION,
                "assistant_intent": AssistantIntent(intent).value,
                "assistant_source_types": [
                    item.value for item in sorted(sources, key=lambda item: item.value)
                ],
                "assistant_evidence_count_band": _count_band(evidence_count),
                "assistant_status": AssistantAnswerStatus(status).value,
                "assistant_refusal_reason": (
                    AssistantRefusalReason(refusal_reason).value
                    if refusal_reason is not None
                    else None
                ),
                "assistant_citation_count": citation_count,
                "assistant_input_token_band": _token_band(input_tokens),
                "assistant_output_token_band": _token_band(output_tokens),
                "assistant_provider_outcome": AssistantProviderOutcome(
                    provider_outcome
                ).value,
                "duration_ms": latency_ms,
            },
        )

    def record_failure(
        self,
        *,
        intent: AssistantIntent,
        sources: tuple[AssistantEvidenceSource, ...],
        evidence_count: int,
        latency_ms: int,
        provider_outcome: AssistantProviderOutcome,
        reason: AssistantFailureReason,
    ) -> None:
        """Record one safe failure category without exception text."""

        _validate_counts(
            sources=sources,
            evidence_count=evidence_count,
            citation_count=0,
            input_tokens=0,
            output_tokens=0,
            latency_ms=latency_ms,
        )
        self._logger.info(
            "assistant_request_failed",
            extra={
                "assistant_policy_version": ASSISTANT_GENERATION_POLICY_VERSION,
                "assistant_intent": AssistantIntent(intent).value,
                "assistant_source_types": [
                    item.value for item in sorted(sources, key=lambda item: item.value)
                ],
                "assistant_evidence_count_band": _count_band(evidence_count),
                "assistant_provider_outcome": AssistantProviderOutcome(
                    provider_outcome
                ).value,
                "assistant_failure_reason": AssistantFailureReason(reason).value,
                "duration_ms": latency_ms,
            },
        )


def _validate_counts(
    *,
    sources: tuple[AssistantEvidenceSource, ...],
    evidence_count: int,
    citation_count: int,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> None:
    resolved_sources = tuple(AssistantEvidenceSource(item) for item in sources)
    if (
        len(resolved_sources) > MAX_EVIDENCE_REQUESTS
        or len(set(resolved_sources)) != len(resolved_sources)
    ):
        raise ValueError("Assistant telemetry sources must be unique and bounded.")
    for value, maximum, label in (
        (evidence_count, MAX_EVIDENCE_RECORDS, "evidence"),
        (citation_count, MAX_CITATIONS, "citation"),
        (input_tokens, MAX_PACKET_INPUT_TOKENS, "input token"),
        (output_tokens, MAX_MODEL_OUTPUT_TOKENS, "output token"),
        (latency_ms, 60_000, "latency"),
    ):
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"Assistant telemetry {label} count is invalid.")


def _count_band(value: int) -> str:
    if value == 0:
        return "000"
    if value <= 3:
        return "001_003"
    if value <= 10:
        return "004_010"
    return "011_020"


def _token_band(value: int) -> str:
    if value == 0:
        return "00000"
    if value <= 1_000:
        return "00001_01000"
    if value <= 4_000:
        return "01001_04000"
    if value <= 16_000:
        return "04001_16000"
    return "16001_32000"


__all__ = [
    "AssistantFailureReason",
    "AssistantMonitor",
    "AssistantProviderOutcome",
]
