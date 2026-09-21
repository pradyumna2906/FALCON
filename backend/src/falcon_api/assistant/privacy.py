"""Owner authorization, prompt allowlists, and the Phase 12 threat model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from falcon_api.assistant.semantics import (
    ASSISTANT_PRIVACY_POLICY_VERSION,
    MAX_PROMPT_COLLECTION_ITEMS,
    MAX_PROMPT_NESTING_DEPTH,
    MAX_PROMPT_TEXT_CHARACTERS,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantThreat,
)


@dataclass(frozen=True, slots=True)
class AssistantSourcePolicy:
    """Prompt-safe top-level fields and ownership requirement for one source."""

    source: AssistantEvidenceSource
    requires_owner: bool
    allowed_fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class AssistantThreatControl:
    """Auditable mitigation and verification for one assistant threat."""

    threat: AssistantThreat
    control: str
    verification: str


_SOURCE_POLICIES = {
    AssistantEvidenceSource.ANALYTICS: AssistantSourcePolicy(
        source=AssistantEvidenceSource.ANALYTICS,
        requires_owner=True,
        allowed_fields=frozenset(
            {
                "snapshot_id",
                "cutoff_at",
                "period_start",
                "period_end",
                "currency",
                "cash_flow",
                "spending_summary",
                "health_score",
                "insights",
                "warnings",
                "policy_versions",
                "reliability",
            }
        ),
    ),
    AssistantEvidenceSource.FORECAST: AssistantSourcePolicy(
        source=AssistantEvidenceSource.FORECAST,
        requires_owner=True,
        allowed_fields=frozenset(
            {
                "run_id",
                "cutoff_at",
                "target",
                "currency",
                "horizon_start",
                "horizon_end",
                "points",
                "confidence_bands",
                "model_name",
                "model_version",
                "quality",
                "warnings",
                "policy_versions",
                "reliability",
            }
        ),
    ),
    AssistantEvidenceSource.GOAL_PROGRESS: AssistantSourcePolicy(
        source=AssistantEvidenceSource.GOAL_PROGRESS,
        requires_owner=True,
        allowed_fields=frozenset(
            {
                "goal_id",
                "name",
                "currency",
                "target_amount",
                "current_amount",
                "remaining_amount",
                "progress_percent",
                "target_date",
                "required_monthly_contribution",
                "status",
                "warnings",
                "cutoff_at",
                "policy_versions",
            }
        ),
    ),
    AssistantEvidenceSource.GOAL_PLAN: AssistantSourcePolicy(
        source=AssistantEvidenceSource.GOAL_PLAN,
        requires_owner=True,
        allowed_fields=frozenset(
            {
                "run_id",
                "cutoff_at",
                "currency",
                "status",
                "goals",
                "periods",
                "allocations",
                "probabilities",
                "shortfalls",
                "safety_reservations",
                "reliability",
                "reason_codes",
                "policy_versions",
            }
        ),
    ),
    AssistantEvidenceSource.SCENARIO_SIMULATION: AssistantSourcePolicy(
        source=AssistantEvidenceSource.SCENARIO_SIMULATION,
        requires_owner=True,
        allowed_fields=frozenset(
            {
                "run_id",
                "cutoff_at",
                "currency",
                "definitions",
                "comparisons",
                "probabilities",
                "percentiles",
                "tail_risk",
                "sensitivity",
                "ranks",
                "recommendation",
                "warnings",
                "policy_versions",
            }
        ),
    ),
    AssistantEvidenceSource.KNOWLEDGE: AssistantSourcePolicy(
        source=AssistantEvidenceSource.KNOWLEDGE,
        requires_owner=False,
        allowed_fields=frozenset(
            {
                "document_id",
                "chunk_id",
                "title",
                "heading",
                "content",
                "version",
                "source_uri",
                "published_at",
                "retired_at",
            }
        ),
    ),
}


_INTENT_SOURCES = {
    AssistantIntent.EXPLAIN_DASHBOARD: frozenset(
        {AssistantEvidenceSource.ANALYTICS, AssistantEvidenceSource.KNOWLEDGE}
    ),
    AssistantIntent.EXPLAIN_FINANCIAL_HEALTH: frozenset(
        {AssistantEvidenceSource.ANALYTICS, AssistantEvidenceSource.KNOWLEDGE}
    ),
    AssistantIntent.SUMMARIZE_SPENDING: frozenset(
        {AssistantEvidenceSource.ANALYTICS, AssistantEvidenceSource.KNOWLEDGE}
    ),
    AssistantIntent.EXPLAIN_SPENDING_SIGNAL: frozenset(
        {AssistantEvidenceSource.ANALYTICS, AssistantEvidenceSource.KNOWLEDGE}
    ),
    AssistantIntent.EXPLAIN_FORECAST: frozenset(
        {
            AssistantEvidenceSource.ANALYTICS,
            AssistantEvidenceSource.FORECAST,
            AssistantEvidenceSource.KNOWLEDGE,
        }
    ),
    AssistantIntent.EXPLAIN_GOAL_PROGRESS: frozenset(
        {
            AssistantEvidenceSource.ANALYTICS,
            AssistantEvidenceSource.GOAL_PROGRESS,
            AssistantEvidenceSource.KNOWLEDGE,
        }
    ),
    AssistantIntent.EXPLAIN_GOAL_PLAN: frozenset(
        {
            AssistantEvidenceSource.FORECAST,
            AssistantEvidenceSource.GOAL_PROGRESS,
            AssistantEvidenceSource.GOAL_PLAN,
            AssistantEvidenceSource.KNOWLEDGE,
        }
    ),
    AssistantIntent.COMPARE_SCENARIOS: frozenset(
        {
            AssistantEvidenceSource.FORECAST,
            AssistantEvidenceSource.GOAL_PLAN,
            AssistantEvidenceSource.SCENARIO_SIMULATION,
            AssistantEvidenceSource.KNOWLEDGE,
        }
    ),
    AssistantIntent.FINANCIAL_EDUCATION: frozenset(
        {AssistantEvidenceSource.KNOWLEDGE}
    ),
    AssistantIntent.UNSUPPORTED: frozenset(),
}


FORBIDDEN_PROMPT_FIELDS = frozenset(
    {
        "user_id",
        "email",
        "password",
        "password_hash",
        "access_token",
        "refresh_token",
        "account_id",
        "account_number",
        "masked_reference",
        "transaction_id",
        "raw_transaction",
        "raw_statement",
        "raw_row",
        "raw_samples",
        "raw_prompt",
        "system_prompt",
        "chain_of_thought",
    }
)


ASSISTANT_THREAT_MODEL = (
    AssistantThreatControl(
        AssistantThreat.CROSS_OWNER_ACCESS,
        "Every private evidence query requires the authenticated owner predicate.",
        "Repository and PostgreSQL integration tests use foreign and missing owners.",
    ),
    AssistantThreatControl(
        AssistantThreat.PROMPT_INJECTION,
        "User text cannot replace system, safety, retrieval, or tool policies.",
        "Adversarial instruction-override prompts must be refused or safely answered.",
    ),
    AssistantThreatControl(
        AssistantThreat.RETRIEVED_INSTRUCTION_INJECTION,
        "Retrieved content is quoted evidence and never executable instruction.",
        "Malicious knowledge chunks cannot alter source or output policy.",
    ),
    AssistantThreatControl(
        AssistantThreat.DATA_EXFILTRATION,
        "Source authorization and the output verifier block unowned evidence.",
        "Cross-owner, enumeration, and indirect disclosure cases return safe failures.",
    ),
    AssistantThreatControl(
        AssistantThreat.SECRET_EXPOSURE,
        "Closed prompt field allowlists exclude credentials and infrastructure secrets.",
        "Nested forbidden-field tests cover every evidence source.",
    ),
    AssistantThreatControl(
        AssistantThreat.RAW_FINANCIAL_EMBEDDING,
        "Raw accounts, statements, and transactions are not embedded or indexed.",
        "Knowledge-ingestion and retrieval contracts reject private raw rows.",
    ),
    AssistantThreatControl(
        AssistantThreat.UNGROUNDED_FINANCIAL_CLAIM,
        "Material financial claims require retrieved evidence and citations.",
        "Numeric consistency, citation completeness, and faithfulness are evaluated.",
    ),
    AssistantThreatControl(
        AssistantThreat.PROHIBITED_FINANCIAL_ACTION,
        "The assistant has no write, transfer, contribution, or approval tool.",
        "Action requests produce a bounded refusal and no financial mutation.",
    ),
    AssistantThreatControl(
        AssistantThreat.UNSAFE_FINANCIAL_ADVICE,
        "Product-specific recommendations and guaranteed outcomes are refused.",
        "Safety evaluation covers investment and certainty-seeking prompts.",
    ),
    AssistantThreatControl(
        AssistantThreat.RAW_PROMPT_LOGGING,
        "Operational telemetry records closed categories rather than prompt text.",
        "Logging allowlist tests reject raw questions, context, and responses.",
    ),
    AssistantThreatControl(
        AssistantThreat.CHAIN_OF_THOUGHT_EXPOSURE,
        "Hidden reasoning is never requested, returned, logged, or persisted.",
        "Public schemas and persistence models contain no reasoning field.",
    ),
)


def source_policy(source: AssistantEvidenceSource) -> AssistantSourcePolicy:
    """Return the immutable policy for a closed evidence source."""

    return _SOURCE_POLICIES[source]


def authorize_evidence_sources(
    *,
    intent: AssistantIntent,
    sources: tuple[AssistantEvidenceSource, ...],
    user_id: UUID | None,
) -> tuple[AssistantSourcePolicy, ...]:
    """Authorize source families before any repository retrieval occurs."""

    if len(set(sources)) != len(sources):
        raise ValueError("Assistant evidence sources must be unique.")
    allowed = _INTENT_SOURCES[intent]
    if any(source not in allowed for source in sources):
        raise PermissionError("Evidence source is not allowed for the resolved intent.")
    policies = tuple(source_policy(source) for source in sources)
    if any(policy.requires_owner for policy in policies) and user_id is None:
        raise PermissionError("Authenticated ownership is required for private evidence.")
    return policies


def prompt_safe_payload(
    source: AssistantEvidenceSource,
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Copy one evidence payload only when every field is prompt-safe."""

    policy = source_policy(source)
    unknown = set(payload) - policy.allowed_fields
    if unknown:
        raise ValueError("Evidence payload contains a field outside its allowlist.")
    return {
        key: _prompt_value(value, depth=1)
        for key, value in payload.items()
    }


def _prompt_value(value: object, *, depth: int) -> Any:
    if depth > MAX_PROMPT_NESTING_DEPTH:
        raise ValueError("Evidence payload exceeds the prompt nesting limit.")
    if value is None or isinstance(value, (bool, int, Decimal, UUID, date, datetime)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("Evidence payload contains a non-finite number.")
        return value
    if isinstance(value, str):
        if len(value) > MAX_PROMPT_TEXT_CHARACTERS:
            raise ValueError("Evidence text exceeds the prompt field limit.")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if len(value) > MAX_PROMPT_COLLECTION_ITEMS:
            raise ValueError("Evidence mapping exceeds the prompt collection limit.")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Evidence mapping keys must be strings.")
            if key.casefold() in FORBIDDEN_PROMPT_FIELDS:
                raise ValueError("Evidence payload contains a forbidden private field.")
            result[key] = _prompt_value(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_PROMPT_COLLECTION_ITEMS:
            raise ValueError("Evidence sequence exceeds the prompt collection limit.")
        return tuple(_prompt_value(item, depth=depth + 1) for item in value)
    raise ValueError("Evidence payload contains an unsupported value type.")


def privacy_policy_version() -> str:
    """Expose the fixed privacy policy without leaking its internal structures."""

    return ASSISTANT_PRIVACY_POLICY_VERSION
