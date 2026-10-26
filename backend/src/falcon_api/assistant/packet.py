"""Bounded, immutable evidence packets for provider-neutral generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from falcon_api.assistant.contracts import AssistantCitation
from falcon_api.assistant.evidence import AssistantEvidenceRecord
from falcon_api.assistant.privacy import (
    authorize_evidence_sources,
    validate_evidence_source_selection,
)
from falcon_api.assistant.semantics import (
    ASSISTANT_CONTRACT_VERSION,
    ASSISTANT_EVIDENCE_POLICY_VERSION,
    ASSISTANT_GENERATION_POLICY_VERSION,
    ASSISTANT_PACKET_POLICY_VERSION,
    ASSISTANT_RETRIEVAL_POLICY_VERSION,
    ASSISTANT_SAFETY_POLICY_VERSION,
    MAX_EVIDENCE_PACKET_CHARACTERS,
    MAX_EVIDENCE_RECORDS,
    MAX_EVIDENCE_REQUESTS,
    MAX_MODEL_OUTPUT_TOKENS,
    MAX_PACKET_INPUT_TOKENS,
    MAX_QUESTION_CHARACTERS,
    MIN_MODEL_OUTPUT_TOKENS,
    MIN_PACKET_INPUT_TOKENS,
    AssistantEvidenceSource,
    AssistantGenerationRule,
    AssistantIntent,
    AssistantReliability,
)


_GENERATION_RULES = tuple(AssistantGenerationRule)
_RELIABILITY_ORDER = {
    AssistantReliability.NORMAL: 0,
    AssistantReliability.PROVISIONAL: 1,
    AssistantReliability.CONSERVATIVE: 2,
    AssistantReliability.UNAVAILABLE: 3,
}
_CORE_INTENT_SOURCES = MappingProxyType(
    {
        AssistantIntent.EXPLAIN_DASHBOARD: frozenset(
            {AssistantEvidenceSource.ANALYTICS}
        ),
        AssistantIntent.EXPLAIN_FINANCIAL_HEALTH: frozenset(
            {AssistantEvidenceSource.ANALYTICS}
        ),
        AssistantIntent.SUMMARIZE_SPENDING: frozenset(
            {AssistantEvidenceSource.ANALYTICS}
        ),
        AssistantIntent.EXPLAIN_SPENDING_SIGNAL: frozenset(
            {AssistantEvidenceSource.ANALYTICS}
        ),
        AssistantIntent.EXPLAIN_FORECAST: frozenset(
            {AssistantEvidenceSource.FORECAST}
        ),
        AssistantIntent.EXPLAIN_GOAL_PROGRESS: frozenset(
            {AssistantEvidenceSource.GOAL_PROGRESS}
        ),
        AssistantIntent.EXPLAIN_GOAL_PLAN: frozenset(
            {AssistantEvidenceSource.GOAL_PLAN}
        ),
        AssistantIntent.COMPARE_SCENARIOS: frozenset(
            {AssistantEvidenceSource.SCENARIO_SIMULATION}
        ),
        AssistantIntent.FINANCIAL_EDUCATION: frozenset(
            {AssistantEvidenceSource.KNOWLEDGE}
        ),
    }
)
_STALE_AFTER = MappingProxyType(
    {
        AssistantEvidenceSource.ANALYTICS: timedelta(days=45),
        AssistantEvidenceSource.FORECAST: timedelta(days=120),
        AssistantEvidenceSource.GOAL_PROGRESS: timedelta(days=45),
        AssistantEvidenceSource.GOAL_PLAN: timedelta(days=120),
        AssistantEvidenceSource.SCENARIO_SIMULATION: timedelta(days=120),
    }
)
_SOURCE_POLICY_VERSIONS = MappingProxyType(
    {
        AssistantEvidenceSource.ANALYTICS: ASSISTANT_EVIDENCE_POLICY_VERSION,
        AssistantEvidenceSource.FORECAST: ASSISTANT_EVIDENCE_POLICY_VERSION,
        AssistantEvidenceSource.GOAL_PROGRESS: ASSISTANT_EVIDENCE_POLICY_VERSION,
        AssistantEvidenceSource.GOAL_PLAN: ASSISTANT_EVIDENCE_POLICY_VERSION,
        AssistantEvidenceSource.SCENARIO_SIMULATION: ASSISTANT_EVIDENCE_POLICY_VERSION,
        AssistantEvidenceSource.KNOWLEDGE: ASSISTANT_RETRIEVAL_POLICY_VERSION,
    }
)


@dataclass(frozen=True, slots=True)
class AssistantEvidencePacket:
    """One replayable model context with no owner identity or database object."""

    question: str = field(repr=False)
    intent: AssistantIntent
    created_at: datetime
    requested_sources: tuple[AssistantEvidenceSource, ...]
    evidence: tuple[AssistantEvidenceRecord, ...] = field(repr=False)
    input_token_budget: int = 16_000
    output_token_budget: int = 1_500
    packet_policy_version: str = ASSISTANT_PACKET_POLICY_VERSION
    generation_policy_version: str = ASSISTANT_GENERATION_POLICY_VERSION
    missing_sources: tuple[AssistantEvidenceSource, ...] = field(init=False)
    missing_required_sources: tuple[AssistantEvidenceSource, ...] = field(init=False)
    stale_evidence_ids: tuple[str, ...] = field(init=False)
    reliability: AssistantReliability = field(init=False)
    estimated_input_tokens: int = field(init=False)
    packet_id: str = field(init=False)

    def __post_init__(self) -> None:
        question = " ".join(self.question.split())
        if not question or len(question) > MAX_QUESTION_CHARACTERS:
            raise ValueError("Packet question must be non-empty and bounded.")
        intent = AssistantIntent(self.intent)
        if intent is AssistantIntent.UNSUPPORTED:
            raise ValueError("Unsupported intents cannot create a generation packet.")
        created_at = _aware(self.created_at, "Packet creation time")
        requested = tuple(AssistantEvidenceSource(item) for item in self.requested_sources)
        if not requested or len(requested) > MAX_EVIDENCE_REQUESTS:
            raise ValueError("Packet sources must be non-empty and bounded.")
        if len(set(requested)) != len(requested):
            raise ValueError("Packet sources must be unique.")
        if not isinstance(self.input_token_budget, int) or isinstance(
            self.input_token_budget, bool
        ) or not (
            MIN_PACKET_INPUT_TOKENS
            <= self.input_token_budget
            <= MAX_PACKET_INPUT_TOKENS
        ):
            raise ValueError("Packet input-token budget is outside policy.")
        if not isinstance(self.output_token_budget, int) or isinstance(
            self.output_token_budget, bool
        ) or not (
            MIN_MODEL_OUTPUT_TOKENS
            <= self.output_token_budget
            <= MAX_MODEL_OUTPUT_TOKENS
        ):
            raise ValueError("Packet output-token budget is outside policy.")
        if self.packet_policy_version != ASSISTANT_PACKET_POLICY_VERSION:
            raise ValueError("Packet policy version is unsupported.")
        if self.generation_policy_version != ASSISTANT_GENERATION_POLICY_VERSION:
            raise ValueError("Generation policy version is unsupported.")

        # The public builder performs the authenticated-owner check before
        # constructing this deliberately owner-free packet.
        validate_evidence_source_selection(
            intent=intent,
            sources=requested,
        )
        required = _CORE_INTENT_SOURCES[intent]
        if not required <= frozenset(requested):
            raise ValueError("Packet sources omit intent-defining evidence.")
        records = _latest_compatible_records(
            self.evidence,
            requested=requested,
            created_at=created_at,
        )
        present_sources = frozenset(item.source for item in records)
        missing = tuple(item for item in requested if item not in present_sources)
        missing_required = tuple(
            item for item in requested if item in required and item not in present_sources
        )
        stale = tuple(
            item.evidence_id
            for item in records
            if _is_stale(item, created_at=created_at)
        )
        reliability = (
            max(
                (item.reliability for item in records),
                key=_RELIABILITY_ORDER.__getitem__,
            )
            if records
            else AssistantReliability.UNAVAILABLE
        )

        object.__setattr__(self, "question", question)
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "requested_sources", requested)
        object.__setattr__(self, "evidence", records)
        object.__setattr__(self, "missing_sources", missing)
        object.__setattr__(self, "missing_required_sources", missing_required)
        object.__setattr__(self, "stale_evidence_ids", stale)
        object.__setattr__(self, "reliability", reliability)

        identity = self._identity_payload()
        packet_id = _sha256(identity)
        object.__setattr__(self, "packet_id", packet_id)
        encoded = _encoded(self._model_payload(packet_id=packet_id))
        if len(encoded) > MAX_EVIDENCE_PACKET_CHARACTERS:
            raise ValueError("Evidence packet exceeds the character limit.")
        estimated_tokens = max(1, (len(encoded) + 3) // 4)
        if estimated_tokens > self.input_token_budget:
            raise ValueError("Evidence packet exceeds its input-token budget.")
        object.__setattr__(self, "estimated_input_tokens", estimated_tokens)

    @property
    def can_generate(self) -> bool:
        """Return whether all intent-defining evidence is present."""

        return bool(self.evidence) and not self.missing_required_sources

    @property
    def citations(self) -> Mapping[str, AssistantCitation]:
        """Return the closed citation map keyed by canonical evidence identity."""

        return MappingProxyType(
            {
                item.evidence_id: AssistantCitation(
                    source=item.source,
                    reference=item.reference,
                    label=item.label,
                    cutoff_at=item.cutoff_at,
                    policy_version=item.policy_version,
                    reliability=item.reliability,
                )
                for item in self.evidence
            }
        )

    def model_payload(self) -> Mapping[str, object]:
        """Return immutable JSON-safe context with instructions isolated."""

        return _freeze(_canonical(self._model_payload(packet_id=self.packet_id)))

    def _identity_payload(self) -> dict[str, object]:
        return {
            "question": self.question,
            "intent": self.intent.value,
            "created_at": self.created_at,
            "requested_sources": tuple(item.value for item in self.requested_sources),
            "missing_sources": tuple(item.value for item in self.missing_sources),
            "missing_required_sources": tuple(
                item.value for item in self.missing_required_sources
            ),
            "stale_evidence_ids": self.stale_evidence_ids,
            "input_token_budget": self.input_token_budget,
            "output_token_budget": self.output_token_budget,
            "packet_policy_version": self.packet_policy_version,
            "generation_policy_version": self.generation_policy_version,
            "contract_version": ASSISTANT_CONTRACT_VERSION,
            "safety_policy_version": ASSISTANT_SAFETY_POLICY_VERSION,
            "evidence": tuple(_record_payload(item) for item in self.evidence),
        }

    def _model_payload(self, *, packet_id: str) -> dict[str, object]:
        versions: dict[str, set[str]] = {}
        for item in self.evidence:
            versions.setdefault(item.source.value, set()).add(item.policy_version)
        return {
            "packet_id": packet_id,
            "contract_version": ASSISTANT_CONTRACT_VERSION,
            "packet_policy_version": self.packet_policy_version,
            "generation_policy_version": self.generation_policy_version,
            "safety_policy_version": ASSISTANT_SAFETY_POLICY_VERSION,
            "instructions": tuple(item.value for item in _GENERATION_RULES),
            "untrusted_user_input": {
                "question": self.question,
                "intent": self.intent.value,
            },
            "retrieval": {
                "created_at": self.created_at,
                "requested_sources": tuple(
                    item.value for item in self.requested_sources
                ),
                "missing_sources": tuple(
                    item.value for item in self.missing_sources
                ),
                "missing_required_sources": tuple(
                    item.value for item in self.missing_required_sources
                ),
                "stale_evidence_ids": self.stale_evidence_ids,
                "source_versions": {
                    source: tuple(sorted(items))
                    for source, items in sorted(versions.items())
                },
                "reliability": self.reliability.value,
            },
            "budgets": {
                "input_tokens": self.input_token_budget,
                "output_tokens": self.output_token_budget,
            },
            "evidence": tuple(_record_payload(item) for item in self.evidence),
        }


def build_evidence_packet(
    *,
    question: str,
    intent: AssistantIntent,
    user_id: UUID | None,
    requested_sources: tuple[AssistantEvidenceSource, ...],
    evidence: tuple[AssistantEvidenceRecord, ...],
    created_at: datetime,
    input_token_budget: int = 16_000,
    output_token_budget: int = 1_500,
) -> AssistantEvidencePacket:
    """Authorize packet sources without retaining the authenticated owner."""

    resolved_intent = AssistantIntent(intent)
    resolved_sources = tuple(AssistantEvidenceSource(item) for item in requested_sources)
    authorize_evidence_sources(
        intent=resolved_intent,
        sources=resolved_sources,
        user_id=user_id,
    )
    return AssistantEvidencePacket(
        question=question,
        intent=resolved_intent,
        created_at=created_at,
        requested_sources=resolved_sources,
        evidence=evidence,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
    )


def _latest_compatible_records(
    records: tuple[AssistantEvidenceRecord, ...],
    *,
    requested: tuple[AssistantEvidenceSource, ...],
    created_at: datetime,
) -> tuple[AssistantEvidenceRecord, ...]:
    if len(records) > MAX_EVIDENCE_RECORDS:
        raise ValueError("Packet evidence exceeds the record limit.")
    identifiers = tuple(item.evidence_id for item in records)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Packet evidence identities must be unique.")
    requested_set = frozenset(requested)
    if any(item.source not in requested_set for item in records):
        raise ValueError("Packet evidence contains an unrequested source.")
    if any(
        item.policy_version != _SOURCE_POLICY_VERSIONS[item.source]
        for item in records
    ):
        raise ValueError("Packet evidence uses an incompatible policy version.")
    if any(item.cutoff_at > created_at for item in records):
        raise ValueError("Packet evidence cannot have a future cutoff.")

    grouped: dict[tuple[AssistantEvidenceSource, str], list[AssistantEvidenceRecord]] = {}
    for item in records:
        grouped.setdefault((item.source, item.reference), []).append(item)
    selected: list[AssistantEvidenceRecord] = []
    for items in grouped.values():
        newest_cutoff = max(item.cutoff_at for item in items)
        newest = tuple(item for item in items if item.cutoff_at == newest_cutoff)
        if len(newest) > 1:
            raise ValueError("Packet evidence contains conflicting current records.")
        selected.append(newest[0])
    source_order = {source: index for index, source in enumerate(requested)}
    selected.sort(
        key=lambda item: (
            source_order[item.source],
            item.reference,
            item.cutoff_at,
            item.evidence_id,
        )
    )
    return tuple(selected)


def _record_payload(record: AssistantEvidenceRecord) -> dict[str, object]:
    return {
        "evidence_id": record.evidence_id,
        "source": record.source.value,
        "reference": record.reference,
        "label": record.label,
        "cutoff_at": record.cutoff_at,
        "policy_version": record.policy_version,
        "reliability": record.reliability.value,
        "facts": record.payload,
    }


def _is_stale(record: AssistantEvidenceRecord, *, created_at: datetime) -> bool:
    threshold = _STALE_AFTER.get(record.source)
    return threshold is not None and created_at - record.cutoff_at > threshold


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")
    return value


def _sha256(value: object) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _encoded(value: object) -> bytes:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _freeze(value: object) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


__all__ = [
    "AssistantEvidencePacket",
    "build_evidence_packet",
]
