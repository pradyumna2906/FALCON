"""Deterministic claim grounding and public answer construction."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from falcon_api.assistant.contracts import AssistantAnswer
from falcon_api.assistant.evidence import AssistantEvidenceRecord
from falcon_api.assistant.model import (
    AssistantModel,
    AssistantModelOutput,
    AssistantModelResult,
)
from falcon_api.assistant.packet import AssistantEvidencePacket
from falcon_api.assistant.semantics import (
    MAX_ANSWER_CHARACTERS,
    AssistantAnswerStatus,
    AssistantClaimKind,
    AssistantEvidenceSource,
    AssistantRefusalReason,
    AssistantReliability,
    AssistantWarning,
)


_NUMERIC_TOKEN_RE = re.compile(
    r"(?<![\w])(?:[₹$€£]\s*)?[+-]?"
    r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?%?(?![\w])"
)
_UNSAFE_OUTPUT_PATTERNS = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.IGNORECASE),
    re.compile(r"\brisk[- ]free\b", re.IGNORECASE),
    re.compile(
        r"\b(?:buy|sell)\s+(?:a\s+)?(?:stock|share|security|crypto|bitcoin)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:invest\s+in|purchase)\b", re.IGNORECASE),
    re.compile(r"\btransfer\s+(?:money|funds?)\b", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(
        r"\bignore\s+(?:all\s+|the\s+|your\s+)?"
        r"(?:instructions|rules|policy)\b",
        re.IGNORECASE,
    ),
)
_IDENTIFIER_KEYS = frozenset(
    {
        "id",
        "snapshot_id",
        "document_id",
        "chunk_id",
        "run_id",
        "goal_id",
        "source_uri",
        "version",
        "model_version",
        "policy_version",
        "policy_versions",
    }
)
_CLAIM_SOURCES = {
    AssistantClaimKind.OBSERVATION: frozenset(
        {
            AssistantEvidenceSource.ANALYTICS,
            AssistantEvidenceSource.GOAL_PROGRESS,
        }
    ),
    AssistantClaimKind.FORECAST: frozenset({AssistantEvidenceSource.FORECAST}),
    AssistantClaimKind.PLAN: frozenset(
        {
            AssistantEvidenceSource.GOAL_PROGRESS,
            AssistantEvidenceSource.GOAL_PLAN,
        }
    ),
    AssistantClaimKind.SIMULATION: frozenset(
        {AssistantEvidenceSource.SCENARIO_SIMULATION}
    ),
    AssistantClaimKind.EDUCATION: frozenset({AssistantEvidenceSource.KNOWLEDGE}),
}
_CLAIM_LABELS = {
    AssistantClaimKind.OBSERVATION: "Observation",
    AssistantClaimKind.FORECAST: "Forecast",
    AssistantClaimKind.PLAN: "Plan",
    AssistantClaimKind.SIMULATION: "Simulation",
    AssistantClaimKind.EDUCATION: "Education",
}


class AssistantGroundingError(RuntimeError):
    """A generated response could not be proven from its cited packet evidence."""


@dataclass(frozen=True, slots=True)
class GroundedAssistantResult:
    """Internal result ready for later persistence or public serialization."""

    answer: AssistantAnswer
    packet_id: str | None
    used_evidence_ids: tuple[str, ...]
    model_result: AssistantModelResult | None
    verified: bool = False


class GroundedAssistantGenerator:
    """Call the model only when core evidence exists, then ground every claim."""

    def __init__(self, model: AssistantModel) -> None:
        self._model = model

    async def generate(
        self,
        packet: AssistantEvidencePacket,
    ) -> GroundedAssistantResult:
        from falcon_api.assistant.safety import screen_packet
        from falcon_api.assistant.verification import verify_model_output

        denied = screen_packet(packet)
        if denied is not None:
            return GroundedAssistantResult(
                answer=denied,
                packet_id=packet.packet_id,
                used_evidence_ids=(),
                model_result=None,
                verified=True,
            )
        if not packet.can_generate:
            return GroundedAssistantResult(
                answer=unavailable_answer(packet),
                packet_id=packet.packet_id,
                used_evidence_ids=(),
                model_result=None,
                verified=True,
            )
        model_result = await self._model.generate(packet)
        answer = verify_model_output(packet, model_result.output)
        used = tuple(dict.fromkeys(
            evidence_id
            for claim in model_result.output.claims
            for evidence_id in claim.evidence_ids
        ))
        return GroundedAssistantResult(
            answer=answer,
            packet_id=packet.packet_id,
            used_evidence_ids=used,
            model_result=model_result,
            verified=True,
        )


def ground_model_output(
    packet: AssistantEvidencePacket,
    output: AssistantModelOutput,
) -> AssistantAnswer:
    """Create a public answer only from claim-level supported output."""

    from falcon_api.assistant.verification import verify_model_output

    return verify_model_output(packet, output)


def unavailable_answer(packet: AssistantEvidencePacket) -> AssistantAnswer:
    """Return a deterministic no-guess answer without invoking a provider."""

    return AssistantAnswer(
        intent=packet.intent,
        status=AssistantAnswerStatus.UNAVAILABLE,
        answer=(
            "I do not have enough verified FALCON evidence to answer that question."
        ),
        evidence_summary=(),
        citations=(),
        reliability=AssistantReliability.UNAVAILABLE,
        warnings=(AssistantWarning.EVIDENCE_INCOMPLETE,),
        suggested_questions=(),
        refusal_reason=AssistantRefusalReason.INSUFFICIENT_EVIDENCE,
    )


def _ground_model_output(
    packet: AssistantEvidencePacket,
    output: AssistantModelOutput,
) -> tuple[AssistantAnswer, tuple[str, ...]]:
    if not packet.can_generate:
        raise AssistantGroundingError("Required packet evidence is unavailable.")
    records = {item.evidence_id: item for item in packet.evidence}
    citation_order: list[str] = []
    answer_parts: list[str] = []
    for claim in output.claims:
        try:
            cited = tuple(records[item] for item in claim.evidence_ids)
        except KeyError as exc:
            raise AssistantGroundingError(
                "A generated claim cites evidence outside the packet."
            ) from exc
        if not any(item.source in _CLAIM_SOURCES[claim.kind] for item in cited):
            raise AssistantGroundingError(
                "A generated claim is not supported by its declared evidence kind."
            )
        _reject_unsafe_output(claim.text)
        _verify_numeric_claim(claim.text, cited)
        markers = []
        for evidence_id in claim.evidence_ids:
            if evidence_id not in citation_order:
                citation_order.append(evidence_id)
            markers.append(str(citation_order.index(evidence_id) + 1))
        marker_text = "".join(f"[{item}]" for item in markers)
        answer_parts.append(
            f"{_CLAIM_LABELS[claim.kind]}: {claim.text} {marker_text}"
        )
    for suggestion in output.suggested_questions:
        _reject_unsafe_output(suggestion)
    answer_text = "\n\n".join(answer_parts)
    if len(answer_text) > MAX_ANSWER_CHARACTERS:
        raise AssistantGroundingError("Grounded answer exceeds the public limit.")

    used_records = tuple(records[item] for item in citation_order)
    reliability = max(
        (item.reliability for item in used_records),
        key=_reliability_rank,
    )
    warnings = _answer_warnings(
        packet,
        used_ids=frozenset(citation_order),
        reliability=reliability,
    )
    limited_warnings = {
        AssistantWarning.EVIDENCE_PROVISIONAL,
        AssistantWarning.EVIDENCE_CONSERVATIVE,
        AssistantWarning.EVIDENCE_INCOMPLETE,
        AssistantWarning.EVIDENCE_STALE,
        AssistantWarning.POLICY_LIMITATION,
    }
    status = (
        AssistantAnswerStatus.LIMITED
        if limited_warnings.intersection(warnings)
        else AssistantAnswerStatus.ANSWERED
    )
    citations = packet.citations
    answer = AssistantAnswer(
        intent=packet.intent,
        status=status,
        answer=answer_text,
        evidence_summary=tuple(
            f"[{index}] {item.label} — {item.source.value}, "
            f"{item.reliability.value}, cutoff {item.cutoff_at.isoformat()}"
            for index, item in enumerate(used_records, start=1)
        ),
        citations=tuple(citations[item] for item in citation_order),
        reliability=reliability,
        warnings=warnings,
        suggested_questions=output.suggested_questions,
    )
    return answer, tuple(citation_order)


def _answer_warnings(
    packet: AssistantEvidencePacket,
    *,
    used_ids: frozenset[str],
    reliability: AssistantReliability,
) -> tuple[AssistantWarning, ...]:
    warnings = []
    if reliability is AssistantReliability.PROVISIONAL:
        warnings.append(AssistantWarning.EVIDENCE_PROVISIONAL)
    elif reliability is AssistantReliability.CONSERVATIVE:
        warnings.append(AssistantWarning.EVIDENCE_CONSERVATIVE)
    if packet.missing_sources:
        warnings.append(AssistantWarning.EVIDENCE_INCOMPLETE)
    if used_ids.intersection(packet.stale_evidence_ids):
        warnings.append(AssistantWarning.EVIDENCE_STALE)
    warnings.append(AssistantWarning.NOT_FINANCIAL_ADVICE)
    return tuple(warnings)


def _verify_numeric_claim(
    text: str,
    evidence: tuple[AssistantEvidenceRecord, ...],
) -> None:
    claimed = _numbers_in_text(text)
    if not claimed:
        return
    supported: set[Decimal] = set()
    for item in evidence:
        _collect_evidence_numbers(item.payload, supported, key=None)
    missing = claimed - supported
    if missing:
        raise AssistantGroundingError(
            "A generated claim contains a number absent from its cited evidence."
        )


def _collect_evidence_numbers(
    value: object,
    result: set[Decimal],
    *,
    key: str | None,
) -> None:
    if key is not None and (
        key in _IDENTIFIER_KEYS or key.endswith("_id") or "sha" in key
    ):
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if number.is_finite():
            result.add(number)
            folded = (key or "").casefold()
            if (
                Decimal("0") <= number <= Decimal("1")
                and any(
                    label in folded
                    for label in ("probability", "rate", "share", "percent")
                )
            ):
                result.add(number * Decimal("100"))
        return
    if isinstance(value, datetime):
        result.update(
            {Decimal(value.year), Decimal(value.month), Decimal(value.day)}
        )
        return
    if isinstance(value, date):
        result.update(
            {Decimal(value.year), Decimal(value.month), Decimal(value.day)}
        )
        return
    if isinstance(value, Enum):
        _collect_evidence_numbers(value.value, result, key=key)
        return
    if isinstance(value, str):
        result.update(_numbers_in_text(value))
        return
    if isinstance(value, Mapping):
        for child_key, item in value.items():
            normalized_key = str(child_key).casefold()
            if (
                normalized_key not in _IDENTIFIER_KEYS
                and not normalized_key.endswith("_id")
                and "sha" not in normalized_key
            ):
                result.update(_numbers_in_text(normalized_key.replace("_", " ")))
            _collect_evidence_numbers(item, result, key=normalized_key)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_evidence_numbers(item, result, key=key)


def _numbers_in_text(value: str) -> set[Decimal]:
    result = set()
    for match in _NUMERIC_TOKEN_RE.finditer(value):
        token = match.group(0)
        normalized = (
            token.replace("₹", "")
            .replace("$", "")
            .replace("€", "")
            .replace("£", "")
            .replace(",", "")
            .replace("%", "")
            .strip()
        )
        try:
            number = Decimal(normalized)
        except InvalidOperation:
            continue
        if number.is_finite():
            result.add(number)
    return result


def _reject_unsafe_output(value: str) -> None:
    if any(pattern.search(value) for pattern in _UNSAFE_OUTPUT_PATTERNS):
        raise AssistantGroundingError(
            "Generated output crosses the financial-safety boundary."
        )


def _reliability_rank(value: AssistantReliability) -> int:
    return {
        AssistantReliability.NORMAL: 0,
        AssistantReliability.PROVISIONAL: 1,
        AssistantReliability.CONSERVATIVE: 2,
        AssistantReliability.UNAVAILABLE: 3,
    }[value]


__all__ = [
    "AssistantGroundingError",
    "GroundedAssistantGenerator",
    "GroundedAssistantResult",
    "ground_model_output",
    "unavailable_answer",
]
