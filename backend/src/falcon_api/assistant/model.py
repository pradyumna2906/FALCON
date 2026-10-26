"""Provider-neutral structured generation with closed operational budgets."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Protocol

from falcon_api.assistant.packet import AssistantEvidencePacket
from falcon_api.assistant.semantics import (
    MAX_ANSWER_CHARACTERS,
    MAX_CITATIONS,
    MAX_MODEL_CLAIM_CHARACTERS,
    MAX_MODEL_CLAIMS,
    MAX_MODEL_COST_MICRO_UNITS,
    MAX_MODEL_IDENTIFIER_CHARACTERS,
    MAX_MODEL_OUTPUT_TOKENS,
    MAX_MODEL_RESPONSE_CHARACTERS,
    MAX_MODEL_RETRIES,
    MAX_MODEL_TIMEOUT_SECONDS,
    MAX_PACKET_INPUT_TOKENS,
    MAX_SUGGESTED_QUESTION_CHARACTERS,
    MAX_SUGGESTED_QUESTIONS,
    MIN_MODEL_OUTPUT_TOKENS,
    MIN_PACKET_INPUT_TOKENS,
    AssistantClaimKind,
)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_EVIDENCE_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_OUTPUT_KEYS = frozenset({"claims", "suggested_questions"})
_CLAIM_KEYS = frozenset({"kind", "text", "evidence_ids"})


class AssistantModelError(RuntimeError):
    """Base safe failure for the provider boundary."""


class AssistantModelUnavailableError(AssistantModelError):
    """Generation is disabled or a safe transient failure was exhausted."""


class AssistantModelTimeoutError(AssistantModelError):
    """The configured generation deadline expired."""


class AssistantModelTransientError(AssistantModelError):
    """A transport may raise this only for an explicitly retry-safe failure."""


class AssistantModelOutputError(AssistantModelError):
    """The provider returned malformed or unsupported structured output."""


class AssistantModelBudgetError(AssistantModelError):
    """The request or measured usage crossed a fixed operational budget."""


@dataclass(frozen=True, slots=True)
class AssistantGeneratedClaim:
    """One material claim and the packet evidence that supports it."""

    kind: AssistantClaimKind
    text: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        kind = AssistantClaimKind(self.kind)
        text = " ".join(self.text.split())
        if not text or len(text) > MAX_MODEL_CLAIM_CHARACTERS:
            raise ValueError("Generated claim text must be non-empty and bounded.")
        evidence_ids = tuple(item.strip() for item in self.evidence_ids)
        if not evidence_ids or len(evidence_ids) > MAX_CITATIONS:
            raise ValueError("Generated claims require bounded evidence references.")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("Generated claim evidence references must be unique.")
        if any(_EVIDENCE_ID_RE.fullmatch(item) is None for item in evidence_ids):
            raise ValueError("Generated claim contains an invalid evidence identity.")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class AssistantModelOutput:
    """Strict provider output before deterministic grounding."""

    claims: tuple[AssistantGeneratedClaim, ...]
    suggested_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        claims = tuple(self.claims)
        if not claims or len(claims) > MAX_MODEL_CLAIMS:
            raise ValueError("Model output requires a bounded claim set.")
        if any(not isinstance(item, AssistantGeneratedClaim) for item in claims):
            raise ValueError("Model output claims must use the closed claim contract.")
        if len({item.text.casefold() for item in claims}) != len(claims):
            raise ValueError("Generated claims must be unique.")
        if sum(len(item.text) for item in claims) > MAX_ANSWER_CHARACTERS:
            raise ValueError("Generated claims exceed the answer limit.")
        if len(self.suggested_questions) > MAX_SUGGESTED_QUESTIONS:
            raise ValueError("Model output contains too many suggested questions.")
        suggestions = tuple(
            " ".join(item.split()) for item in self.suggested_questions
        )
        if any(
            not item or len(item) > MAX_SUGGESTED_QUESTION_CHARACTERS
            for item in suggestions
        ):
            raise ValueError("Suggested questions must be non-empty and bounded.")
        if len({item.casefold() for item in suggestions}) != len(suggestions):
            raise ValueError("Suggested questions must be unique.")
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "suggested_questions", suggestions)


@dataclass(frozen=True, slots=True)
class AssistantModelUsage:
    """Internal aggregate usage; never part of the public assistant response."""

    input_tokens: int
    output_tokens: int
    cost_micro_units: int

    def __post_init__(self) -> None:
        for label, value in (
            ("input tokens", self.input_tokens),
            ("output tokens", self.output_tokens),
            ("cost", self.cost_micro_units),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Model {label} must be a non-negative integer.")


@dataclass(frozen=True, slots=True)
class AssistantModelTransportResponse:
    """Provider transport result stripped of headers, secrets, and raw metadata."""

    content: str = field(repr=False)
    usage: AssistantModelUsage

    def __post_init__(self) -> None:
        if (
            not isinstance(self.content, str)
            or not self.content
            or len(self.content) > MAX_MODEL_RESPONSE_CHARACTERS
        ):
            raise ValueError("Model response content must be non-empty and bounded.")


@dataclass(frozen=True, slots=True)
class AssistantModelConfiguration:
    """Provider-independent limits for one approved model deployment."""

    provider_id: str
    model_id: str
    temperature: Decimal = Decimal("0")
    timeout_seconds: float = 20.0
    max_input_tokens: int = 16_000
    max_output_tokens: int = 1_500
    max_cost_micro_units: int = 1_000_000
    transient_retries: int = 1

    def __post_init__(self) -> None:
        provider = _identifier(self.provider_id, "provider")
        model = _identifier(self.model_id, "model")
        try:
            temperature = Decimal(str(self.temperature))
        except InvalidOperation as exc:
            raise ValueError("Model temperature is invalid.") from exc
        if not temperature.is_finite() or not Decimal("0") <= temperature <= Decimal("0.2"):
            raise ValueError("Model temperature must be between 0 and 0.2.")
        if isinstance(self.timeout_seconds, bool) or not (
            0 < self.timeout_seconds <= MAX_MODEL_TIMEOUT_SECONDS
        ):
            raise ValueError("Model timeout is outside policy.")
        if not isinstance(self.max_input_tokens, int) or isinstance(
            self.max_input_tokens, bool
        ) or not (
            MIN_PACKET_INPUT_TOKENS
            <= self.max_input_tokens
            <= MAX_PACKET_INPUT_TOKENS
        ):
            raise ValueError("Model input-token limit is outside policy.")
        if not isinstance(self.max_output_tokens, int) or isinstance(
            self.max_output_tokens, bool
        ) or not (
            MIN_MODEL_OUTPUT_TOKENS
            <= self.max_output_tokens
            <= MAX_MODEL_OUTPUT_TOKENS
        ):
            raise ValueError("Model output-token limit is outside policy.")
        if not isinstance(self.max_cost_micro_units, int) or isinstance(
            self.max_cost_micro_units, bool
        ) or not (
            0 < self.max_cost_micro_units <= MAX_MODEL_COST_MICRO_UNITS
        ):
            raise ValueError("Model cost limit is outside policy.")
        if not isinstance(self.transient_retries, int) or isinstance(
            self.transient_retries, bool
        ) or not (
            0 <= self.transient_retries <= MAX_MODEL_RETRIES
        ):
            raise ValueError("Model retry count is outside policy.")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "model_id", model)
        object.__setattr__(self, "temperature", temperature)


@dataclass(frozen=True, slots=True)
class AssistantModelRequest:
    """Closed request passed to an externally configured transport."""

    request_id: str
    model_id: str
    payload: Mapping[str, object] = field(repr=False)
    response_schema: Mapping[str, object] = field(repr=False)
    temperature: Decimal
    max_output_tokens: int
    max_cost_micro_units: int
    tools: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        if _EVIDENCE_ID_RE.fullmatch(self.request_id) is None:
            raise ValueError("Model request ID must be a packet identity.")
        if self.tools:
            raise ValueError("Assistant generation cannot receive tools.")
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "response_schema", _freeze(self.response_schema))

    def payload_json(self) -> str:
        """Serialize the already bounded packet without provider-specific objects."""

        return _json_document(self.payload)

    def response_schema_json(self) -> str:
        """Serialize the strict response schema for transports that require JSON."""

        return _json_document(self.response_schema)


@dataclass(frozen=True, slots=True)
class AssistantModelResult:
    """Validated internal generation and bounded usage metadata."""

    output: AssistantModelOutput
    usage: AssistantModelUsage
    provider_id: str
    model_id: str


class AssistantModel(Protocol):
    """Replaceable generation boundary used by the application layer."""

    async def generate(
        self,
        packet: AssistantEvidencePacket,
    ) -> AssistantModelResult: ...


class AssistantModelTransport(Protocol):
    """Approved deployment transport; authentication stays outside the request."""

    async def complete(
        self,
        request: AssistantModelRequest,
    ) -> AssistantModelTransportResponse: ...


class DisabledAssistantModel:
    """Fail closed when no approved provider transport is configured."""

    async def generate(
        self,
        packet: AssistantEvidencePacket,
    ) -> AssistantModelResult:
        del packet
        raise AssistantModelUnavailableError("Assistant generation is not configured.")


class StructuredAssistantModel:
    """Enforce timeout, retry, budget, schema, and evidence-reference policy."""

    def __init__(
        self,
        *,
        transport: AssistantModelTransport,
        configuration: AssistantModelConfiguration,
    ) -> None:
        self._transport = transport
        self._configuration = configuration

    async def generate(
        self,
        packet: AssistantEvidencePacket,
    ) -> AssistantModelResult:
        if not packet.can_generate:
            raise AssistantModelOutputError(
                "Required evidence is unavailable for generation."
            )
        configuration = self._configuration
        if packet.estimated_input_tokens > configuration.max_input_tokens:
            raise AssistantModelBudgetError("Model input-token budget was exceeded.")
        output_tokens = min(
            packet.output_token_budget,
            configuration.max_output_tokens,
        )
        request = AssistantModelRequest(
            request_id=packet.packet_id,
            model_id=configuration.model_id,
            payload=packet.model_payload(),
            response_schema=_MODEL_RESPONSE_SCHEMA,
            temperature=configuration.temperature,
            max_output_tokens=output_tokens,
            max_cost_micro_units=configuration.max_cost_micro_units,
        )
        response = await self._complete(request)
        if response.usage.input_tokens > configuration.max_input_tokens:
            raise AssistantModelBudgetError("Measured input usage exceeded policy.")
        if response.usage.output_tokens > output_tokens:
            raise AssistantModelBudgetError("Measured output usage exceeded policy.")
        if response.usage.cost_micro_units > configuration.max_cost_micro_units:
            raise AssistantModelBudgetError("Measured model cost exceeded policy.")
        output = parse_model_output(response.content)
        permitted = frozenset(item.evidence_id for item in packet.evidence)
        referenced = {
            evidence_id
            for claim in output.claims
            for evidence_id in claim.evidence_ids
        }
        if not referenced <= permitted:
            raise AssistantModelOutputError(
                "Model output references evidence outside the packet."
            )
        return AssistantModelResult(
            output=output,
            usage=response.usage,
            provider_id=configuration.provider_id,
            model_id=configuration.model_id,
        )

    async def _complete(
        self,
        request: AssistantModelRequest,
    ) -> AssistantModelTransportResponse:
        retries = self._configuration.transient_retries
        for attempt in range(retries + 1):
            try:
                async with asyncio.timeout(self._configuration.timeout_seconds):
                    return await self._transport.complete(request)
            except AssistantModelTransientError as exc:
                if attempt == retries:
                    raise AssistantModelUnavailableError(
                        "Assistant provider is temporarily unavailable."
                    ) from exc
            except TimeoutError as exc:
                raise AssistantModelTimeoutError(
                    "Assistant generation exceeded its deadline."
                ) from exc
        raise AssertionError("Unreachable model retry state.")


def parse_model_output(content: str) -> AssistantModelOutput:
    """Parse one duplicate-key-safe, additional-property-free JSON response."""

    if (
        not isinstance(content, str)
        or not content
        or len(content) > MAX_MODEL_RESPONSE_CHARACTERS
    ):
        raise AssistantModelOutputError("Model output is empty or oversized.")
    try:
        payload = json.loads(content, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AssistantModelOutputError("Model output is not strict JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != _OUTPUT_KEYS:
        raise AssistantModelOutputError("Model output has an invalid top-level shape.")
    claims_value = payload["claims"]
    suggestions_value = payload["suggested_questions"]
    if not isinstance(claims_value, list) or not isinstance(suggestions_value, list):
        raise AssistantModelOutputError("Model output collections are invalid.")
    claims = []
    try:
        for value in claims_value:
            if not isinstance(value, dict) or set(value) != _CLAIM_KEYS:
                raise AssistantModelOutputError("A generated claim has an invalid shape.")
            evidence_ids = value["evidence_ids"]
            if not isinstance(evidence_ids, list) or any(
                not isinstance(item, str) for item in evidence_ids
            ):
                raise AssistantModelOutputError(
                    "Generated claim evidence references are invalid."
                )
            if not isinstance(value["kind"], str) or not isinstance(value["text"], str):
                raise AssistantModelOutputError("Generated claim values are invalid.")
            claims.append(
                AssistantGeneratedClaim(
                    kind=AssistantClaimKind(value["kind"]),
                    text=value["text"],
                    evidence_ids=tuple(evidence_ids),
                )
            )
        if any(not isinstance(item, str) for item in suggestions_value):
            raise AssistantModelOutputError("Suggested questions must be strings.")
        return AssistantModelOutput(
            claims=tuple(claims),
            suggested_questions=tuple(suggestions_value),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, AssistantModelOutputError):
            raise
        raise AssistantModelOutputError("Model output violates the response contract.") from exc


def model_response_schema() -> Mapping[str, object]:
    """Expose the immutable schema supplied to every configured provider."""

    return _MODEL_RESPONSE_SCHEMA


def _identifier(value: str, label: str) -> str:
    resolved = value.strip()
    if (
        not resolved
        or len(resolved) > MAX_MODEL_IDENTIFIER_CHARACTERS
        or _IDENTIFIER_RE.fullmatch(resolved) is None
    ):
        raise ValueError(f"Assistant {label} identifier is invalid.")
    return resolved


def _unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _freeze(value: object) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_document(value: object) -> str:
    return json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


_MODEL_RESPONSE_SCHEMA = _freeze(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["claims", "suggested_questions"],
        "properties": {
            "claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_MODEL_CLAIMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "text", "evidence_ids"],
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [item.value for item in AssistantClaimKind],
                        },
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_MODEL_CLAIM_CHARACTERS,
                        },
                        "evidence_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": MAX_CITATIONS,
                            "uniqueItems": True,
                            "items": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                        },
                    },
                },
            },
            "suggested_questions": {
                "type": "array",
                "maxItems": MAX_SUGGESTED_QUESTIONS,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_SUGGESTED_QUESTION_CHARACTERS,
                },
            },
        },
    }
)


__all__ = [
    "AssistantGeneratedClaim",
    "AssistantModel",
    "AssistantModelBudgetError",
    "AssistantModelConfiguration",
    "AssistantModelError",
    "AssistantModelOutput",
    "AssistantModelOutputError",
    "AssistantModelRequest",
    "AssistantModelResult",
    "AssistantModelTimeoutError",
    "AssistantModelTransientError",
    "AssistantModelTransport",
    "AssistantModelTransportResponse",
    "AssistantModelUnavailableError",
    "AssistantModelUsage",
    "DisabledAssistantModel",
    "StructuredAssistantModel",
    "model_response_schema",
    "parse_model_output",
]
