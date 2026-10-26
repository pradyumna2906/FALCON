"""Final deterministic gate for model claims, units, citations, and disclosure."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from falcon_api.assistant.contracts import AssistantAnswer
from falcon_api.assistant.evidence import AssistantEvidenceRecord
from falcon_api.assistant.grounding import AssistantGroundingError, _ground_model_output
from falcon_api.assistant.model import AssistantModelOutput
from falcon_api.assistant.packet import AssistantEvidencePacket
from falcon_api.assistant.safety import screen_packet, screen_public_text
from falcon_api.assistant.semantics import (
    AssistantAnswerStatus,
    AssistantClaimKind,
    AssistantEvidenceSource,
    AssistantWarning,
)


_NUMBER = re.compile(
    r"(?<![\w])(?:(?P<prefix_code>INR|USD|EUR|GBP)\s+)?"
    r"(?P<unit>[₹$€£])?\s*"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?)"
    r"(?P<percent>%|\s+percent(?:age)?)?"
    r"(?:\s+(?P<suffix_code>INR|USD|EUR|GBP)\b)?(?![\w])",
    re.IGNORECASE,
)
_CURRENCIES = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}
_KIND_SOURCE = {
    AssistantClaimKind.OBSERVATION: {AssistantEvidenceSource.ANALYTICS, AssistantEvidenceSource.GOAL_PROGRESS},
    AssistantClaimKind.FORECAST: {AssistantEvidenceSource.FORECAST},
    AssistantClaimKind.PLAN: {AssistantEvidenceSource.GOAL_PROGRESS, AssistantEvidenceSource.GOAL_PLAN},
    AssistantClaimKind.SIMULATION: {AssistantEvidenceSource.SCENARIO_SIMULATION},
    AssistantClaimKind.EDUCATION: {AssistantEvidenceSource.KNOWLEDGE},
}
_CERTAINTY = re.compile(r"\b(?:will definitely|will certainly|is guaranteed|must happen|cannot fail|100% certain)\b", re.I)


class AssistantVerificationError(AssistantGroundingError):
    """Generated material cannot be safely served or persisted."""


def verify_model_output(packet: AssistantEvidencePacket, output: AssistantModelOutput) -> AssistantAnswer:
    """Check model output after generation; derive the public answer on success."""

    if screen_packet(packet) is not None:
        raise AssistantVerificationError("Unsafe packet cannot produce a generated answer.")
    try:
        answer, used_ids = _ground_model_output(packet, output)
        records = {item.evidence_id: item for item in packet.evidence}
        for claim in output.claims:
            screen_public_text(claim.text)
            cited = tuple(records[item] for item in claim.evidence_ids)
            authoritative = tuple(item for item in cited if item.source in _KIND_SOURCE[claim.kind])
            if not authoritative:
                raise AssistantVerificationError("Claim kind has no authoritative cited source.")
            _verify_units(claim.text, authoritative)
            if claim.kind in (AssistantClaimKind.FORECAST, AssistantClaimKind.SIMULATION) and _CERTAINTY.search(claim.text):
                raise AssistantVerificationError("Predictions cannot be stated as certain outcomes.")
        for suggestion in output.suggested_questions:
            screen_public_text(suggestion)
        if len(answer.citations) != len(used_ids) or len(answer.evidence_summary) != len(used_ids):
            raise AssistantVerificationError("Answer citations are incomplete.")
        if answer.answer.count("[") != sum(len(claim.evidence_ids) for claim in output.claims):
            raise AssistantVerificationError("Answer claim markers are incomplete.")
        if AssistantWarning.NOT_FINANCIAL_ADVICE not in answer.warnings:
            raise AssistantVerificationError("Public financial disclaimer is absent.")
        if packet.stale_evidence_ids and any(item in packet.stale_evidence_ids for item in used_ids):
            if AssistantWarning.EVIDENCE_STALE not in answer.warnings or answer.status is not AssistantAnswerStatus.LIMITED:
                raise AssistantVerificationError("Stale evidence requires a limited answer.")
        if packet.missing_sources and (AssistantWarning.EVIDENCE_INCOMPLETE not in answer.warnings or answer.status is not AssistantAnswerStatus.LIMITED):
            raise AssistantVerificationError("Missing optional evidence must be disclosed.")
        return answer
    except (ValueError, KeyError, AssistantGroundingError) as exc:
        if isinstance(exc, AssistantVerificationError):
            raise
        message = str(exc) if isinstance(exc, AssistantGroundingError) else "Generated answer failed the final verification gate."
        raise AssistantVerificationError(message) from exc


def _verify_units(text: str, records: tuple[AssistantEvidenceRecord, ...]) -> None:
    """A cited authoritative value must also support its displayed unit."""

    for match in _NUMBER.finditer(text):
        try:
            number = Decimal(match.group("number").replace(",", ""))
        except InvalidOperation as exc:
            raise AssistantVerificationError("Invalid claim number.") from exc
        symbol_currency = _CURRENCIES.get(match.group("unit"))
        code_currency = (match.group("prefix_code") or match.group("suffix_code") or "").upper() or None
        if symbol_currency and code_currency and symbol_currency != code_currency:
            raise AssistantVerificationError("Claim uses conflicting currency units.")
        currency = symbol_currency or code_currency
        percent = bool(match.group("percent"))
        if not any(_supports(number, record, currency=currency, percent=percent) for record in records):
            raise AssistantVerificationError("Claim number or unit lacks cited authoritative support.")


def _supports(number: Decimal, record: AssistantEvidenceRecord, *, currency: str | None, percent: bool) -> bool:
    declared_currency = str(record.payload.get("currency", "")).upper()
    if currency and declared_currency != currency:
        # Public educational text may quote its own currency-marked example.
        if record.source is not AssistantEvidenceSource.KNOWLEDGE:
            return False
    for value, key, marked_currency, marked_percent in _facts(record.payload):
        if currency:
            if marked_currency and marked_currency != currency:
                continue
            if not marked_currency and declared_currency != currency:
                continue
        if percent:
            if marked_percent or any(label in key for label in ("probability", "rate", "percent", "share")):
                if number == value or (Decimal(0) <= value <= Decimal(1) and number == value * 100):
                    return True
            continue
        if value == number:
            return True
    return False


def _facts(value: object, key: str = "") -> list[tuple[Decimal, str, str | None, bool]]:
    if key.endswith("_id") or key in {"id", "version", "model_version", "policy_version", "source_uri", "run_id", "snapshot_id"}:
        return []
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float, Decimal)):
        return [(Decimal(str(value)), key, None, False)]
    if isinstance(value, (datetime, date)):
        return [(Decimal(item), key, None, False) for item in (value.year, value.month, value.day)]
    if isinstance(value, str):
        result = []
        for match in _NUMBER.finditer(value):
            result.append((
                Decimal(match.group("number").replace(",", "")),
                key,
                _CURRENCIES.get(match.group("unit")) or (match.group("prefix_code") or match.group("suffix_code") or "").upper() or None,
                bool(match.group("percent")),
            ))
        return result
    if isinstance(value, Mapping):
        result = []
        for child_key, child in value.items():
            normalized = str(child_key).casefold()
            # Confidence level appears in keys such as lower_80 / upper_80.
            if normalized.startswith(("lower_", "upper_")) and normalized.rsplit("_", 1)[-1].isdigit():
                result.append((Decimal(normalized.rsplit("_", 1)[-1]), normalized, None, True))
            result.extend(_facts(child, normalized))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [fact for item in value for fact in _facts(item, key)]
    return []


__all__ = ["AssistantVerificationError", "verify_model_output"]
