"""Provider-neutral model boundary tests for Phase 12 Checkpoint 12.7."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.assistant import (
    AssistantClaimKind,
    AssistantEvidenceRecord,
    AssistantEvidenceSource,
    AssistantGeneratedClaim,
    AssistantIntent,
    AssistantModelBudgetError,
    AssistantModelConfiguration,
    AssistantModelOutput,
    AssistantModelOutputError,
    AssistantModelRequest,
    AssistantModelTimeoutError,
    AssistantModelTransientError,
    AssistantModelTransportResponse,
    AssistantModelUnavailableError,
    AssistantModelUsage,
    AssistantReliability,
    DisabledAssistantModel,
    StructuredAssistantModel,
    build_evidence_packet,
    model_response_schema,
    parse_model_output,
)


NOW = datetime(2026, 9, 22, 10, tzinfo=UTC)
OWNER_ID = uuid4()


def _packet(*, evidence: bool = True):
    record = AssistantEvidenceRecord(
        source=AssistantEvidenceSource.FORECAST,
        reference="forecast-1",
        label="Savings forecast",
        cutoff_at=NOW,
        policy_version="2026.1",
        reliability=AssistantReliability.NORMAL,
        payload={"points": ({"expected_value": Decimal("8500")},)},
    )
    packet = build_evidence_packet(
        question="Explain my savings forecast",
        intent=AssistantIntent.EXPLAIN_FORECAST,
        user_id=OWNER_ID,
        requested_sources=(AssistantEvidenceSource.FORECAST,),
        evidence=(record,) if evidence else (),
        created_at=NOW,
    )
    return packet, record


def _content(evidence_id: str, **changes) -> str:
    payload = {
        "claims": [
            {
                "kind": "forecast",
                "text": "Expected savings are ₹8,500.",
                "evidence_ids": [evidence_id],
            }
        ],
        "suggested_questions": ["How reliable is this forecast?"],
    }
    payload.update(changes)
    return json.dumps(payload)


def _response(content: str, **usage) -> AssistantModelTransportResponse:
    values = {"input_tokens": 500, "output_tokens": 100, "cost_micro_units": 50}
    values.update(usage)
    return AssistantModelTransportResponse(
        content=content,
        usage=AssistantModelUsage(**values),
    )


class FakeTransport:
    def __init__(self, *results):
        self.results = list(results)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _model(transport, **changes) -> StructuredAssistantModel:
    values = {
        "provider_id": "approved-provider",
        "model_id": "grounded-model-v1",
        "temperature": Decimal("0"),
    }
    values.update(changes)
    return StructuredAssistantModel(
        transport=transport,
        configuration=AssistantModelConfiguration(**values),
    )


def test_structured_model_sends_closed_request_and_validates_result() -> None:
    packet, record = _packet()
    transport = FakeTransport(_response(_content(record.evidence_id)))

    result = asyncio.run(_model(transport).generate(packet))

    assert result.output.claims[0].kind is AssistantClaimKind.FORECAST
    assert result.provider_id == "approved-provider"
    assert result.model_id == "grounded-model-v1"
    request = transport.requests[0]
    assert request.request_id == packet.packet_id
    assert request.temperature == Decimal("0")
    assert request.tools == ()
    assert request.payload["packet_id"] == packet.packet_id
    assert request.response_schema["additionalProperties"] is False
    assert json.loads(request.payload_json())["packet_id"] == packet.packet_id
    assert json.loads(request.response_schema_json())["type"] == "object"
    with pytest.raises(TypeError):
        request.payload["packet_id"] = "changed"


def test_model_retries_only_explicit_transient_failure() -> None:
    packet, record = _packet()
    transport = FakeTransport(
        AssistantModelTransientError("temporary"),
        _response(_content(record.evidence_id)),
    )

    result = asyncio.run(_model(transport, transient_retries=1).generate(packet))

    assert result.output.claims[0].evidence_ids == (record.evidence_id,)
    assert len(transport.requests) == 2

    exhausted = FakeTransport(
        AssistantModelTransientError("temporary"),
        AssistantModelTransientError("temporary"),
    )
    with pytest.raises(AssistantModelUnavailableError, match="temporarily"):
        asyncio.run(_model(exhausted, transient_retries=1).generate(packet))


def test_model_timeout_fails_closed_without_retrying() -> None:
    packet, _ = _packet()

    class SlowTransport:
        def __init__(self):
            self.calls = 0

        async def complete(self, request):
            del request
            self.calls += 1
            await asyncio.sleep(0.05)
            raise AssertionError("unreachable")

    transport = SlowTransport()
    with pytest.raises(AssistantModelTimeoutError, match="deadline"):
        asyncio.run(
            _model(
                transport,
                timeout_seconds=0.001,
                transient_retries=2,
            ).generate(packet)
        )
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("usage", "message"),
    [
        ({"input_tokens": 16_001}, "input usage"),
        ({"output_tokens": 1_501}, "output usage"),
        ({"cost_micro_units": 1_000_001}, "cost"),
    ],
)
def test_model_rejects_measured_budget_overrun(usage, message) -> None:
    packet, record = _packet()
    transport = FakeTransport(_response(_content(record.evidence_id), **usage))

    with pytest.raises(AssistantModelBudgetError, match=message):
        asyncio.run(_model(transport).generate(packet))


def test_model_rejects_packet_without_required_evidence_before_transport() -> None:
    packet, _ = _packet(evidence=False)
    transport = FakeTransport()

    with pytest.raises(AssistantModelOutputError, match="Required evidence"):
        asyncio.run(_model(transport).generate(packet))
    assert transport.requests == []


def test_model_rejects_reference_outside_packet() -> None:
    packet, _ = _packet()
    transport = FakeTransport(_response(_content("f" * 64)))

    with pytest.raises(AssistantModelOutputError, match="outside the packet"):
        asyncio.run(_model(transport).generate(packet))


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"claims": [], "claims": [], "suggested_questions": []}',
        '{"claims": [], "suggested_questions": [], "reasoning": "hidden"}',
        '{"claims": "wrong", "suggested_questions": []}',
        '{"claims": [{"kind": "forecast", "text": "x", "evidence_ids": [], "extra": true}], "suggested_questions": []}',
        '{"claims": [{"kind": "unknown", "text": "x", "evidence_ids": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}], "suggested_questions": []}',
    ],
)
def test_parser_rejects_malformed_or_extended_output(content: str) -> None:
    with pytest.raises(AssistantModelOutputError):
        parse_model_output(content)


def test_parser_normalizes_valid_claims_and_suggestions() -> None:
    output = parse_model_output(
        _content(
            "a" * 64,
            suggested_questions=["  What changes this forecast?  "],
        )
    )

    assert output.claims[0].text == "Expected savings are ₹8,500."
    assert output.suggested_questions == ("What changes this forecast?",)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"provider_id": "bad provider"}, "provider"),
        ({"model_id": ""}, "model"),
        ({"temperature": Decimal("0.3")}, "temperature"),
        ({"timeout_seconds": 0}, "timeout"),
        ({"max_input_tokens": 100}, "input-token"),
        ({"max_output_tokens": 100}, "output-token"),
        ({"max_cost_micro_units": 0}, "cost"),
        ({"transient_retries": 3}, "retry"),
        ({"transient_retries": 1.5}, "retry"),
    ],
)
def test_model_configuration_rejects_unsafe_values(changes, message) -> None:
    values = {"provider_id": "provider", "model_id": "model"}
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        AssistantModelConfiguration(**values)


def test_internal_usage_and_transport_contracts_are_bounded() -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        AssistantModelUsage(input_tokens=1.5, output_tokens=0, cost_micro_units=0)
    with pytest.raises(ValueError, match="non-empty and bounded"):
        AssistantModelTransportResponse(
            content="",
            usage=AssistantModelUsage(0, 0, 0),
        )


def test_model_request_rejects_tools_and_schema_is_immutable() -> None:
    packet, _ = _packet()
    with pytest.raises(ValueError, match="cannot receive tools"):
        AssistantModelRequest(
            request_id=packet.packet_id,
            model_id="model",
            payload=packet.model_payload(),
            response_schema=model_response_schema(),
            temperature=Decimal("0"),
            max_output_tokens=500,
            max_cost_micro_units=1_000,
            tools=(object(),),
        )
    schema = model_response_schema()
    with pytest.raises(TypeError):
        schema["type"] = "array"


def test_disabled_model_never_generates() -> None:
    packet, _ = _packet()
    with pytest.raises(AssistantModelUnavailableError, match="not configured"):
        asyncio.run(DisabledAssistantModel().generate(packet))


def test_generated_output_contract_rejects_duplicate_claims() -> None:
    claim = AssistantGeneratedClaim(
        kind=AssistantClaimKind.FORECAST,
        text="A supported forecast statement.",
        evidence_ids=("a" * 64,),
    )
    with pytest.raises(ValueError, match="claims must be unique"):
        AssistantModelOutput(claims=(claim, claim))
