"""Owner-scoped retrieval adapters for authoritative FALCON evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.application import AnalyticsSelection, FinancialAnalyticsService
from falcon_api.analytics.semantics import AnalyticsComparisonMode, AnalyticsConfidenceLevel
from falcon_api.analytics.types import AnalyticsGranularity
from falcon_api.assistant.privacy import authorize_evidence_sources, prompt_safe_payload
from falcon_api.assistant.semantics import (
    ASSISTANT_EVIDENCE_POLICY_VERSION,
    MAX_CITATION_LABEL_CHARACTERS,
    MAX_EVIDENCE_RECORDS,
    MAX_EVIDENCE_REQUESTS,
    MAX_KNOWLEDGE_QUERY_CHARACTERS,
    MAX_SOURCE_REFERENCE_CHARACTERS,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantKnowledgeTopic,
    AssistantReliability,
)
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.forecasting.persistence import ForecastPersistenceRepository
from falcon_api.goal_planning.contributions import ContributionService
from falcon_api.goal_planning.persistence import GoalPlanRepository
from falcon_api.goal_planning.semantics import GOAL_PLANNING_CONTRACT_VERSION
from falcon_api.scenario_simulation.persistence import ScenarioSimulationRepository


_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class AssistantEvidenceQuery:
    """Internal server-owned selection for one evidence family."""

    source: AssistantEvidenceSource
    reference_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    trusted_timezone: str | None = None
    currency: str | None = None
    text: str | None = None
    topics: tuple[AssistantKnowledgeTopic, ...] = ()
    limit: int = 5

    def __post_init__(self) -> None:
        source = AssistantEvidenceSource(self.source)
        object.__setattr__(self, "source", source)
        if isinstance(self.limit, bool) or not 1 <= self.limit <= 25:
            raise ValueError("Evidence query limit must be between 1 and 25.")
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("Evidence date ranges require both boundaries.")
        if self.date_from is not None and self.date_to is not None:
            if self.date_to < self.date_from:
                raise ValueError("Evidence date range must be ordered.")
            if (self.date_to - self.date_from).days >= 366:
                raise ValueError("Evidence date range cannot exceed 366 days.")
        currency = self.currency.strip().upper() if self.currency else None
        if currency is not None and _CURRENCY_RE.fullmatch(currency) is None:
            raise ValueError("Evidence currency must be an ISO-like code.")
        object.__setattr__(self, "currency", currency)
        timezone = self.trusted_timezone.strip() if self.trusted_timezone else None
        object.__setattr__(self, "trusted_timezone", timezone)
        text = self.text.strip() if self.text else None
        if text is not None and len(text) > MAX_KNOWLEDGE_QUERY_CHARACTERS:
            raise ValueError("Knowledge query exceeds the character limit.")
        object.__setattr__(self, "text", text)
        topics = tuple(AssistantKnowledgeTopic(item) for item in self.topics)
        if len(set(topics)) != len(topics):
            raise ValueError("Knowledge query topics must be unique.")
        object.__setattr__(self, "topics", topics)
        self._validate_shape()

    def _validate_shape(self) -> None:
        if self.source is AssistantEvidenceSource.KNOWLEDGE:
            if self.text is None or self.reference_id is not None:
                raise ValueError("Knowledge evidence requires text and no resource ID.")
            if any((self.date_from, self.date_to, self.trusted_timezone, self.currency)):
                raise ValueError("Knowledge evidence cannot select private context.")
            return
        if self.text is not None or self.topics:
            raise ValueError("Private evidence cannot contain a knowledge query.")
        if self.source is AssistantEvidenceSource.ANALYTICS:
            if self.reference_id is not None:
                raise ValueError("Analytics evidence is selected by a trusted range.")
            if self.trusted_timezone is None or self.currency is None:
                raise ValueError("Analytics evidence requires timezone and currency.")
            return
        if self.reference_id is None:
            raise ValueError("Resource evidence requires a server-selected ID.")
        if self.source is AssistantEvidenceSource.GOAL_PROGRESS:
            if self.trusted_timezone is None:
                raise ValueError("Goal progress requires the trusted timezone.")
            if any((self.date_from, self.date_to, self.currency)):
                raise ValueError("Goal progress accepts only its trusted timezone.")
        elif any((self.date_from, self.date_to, self.trusted_timezone, self.currency)):
            raise ValueError("Persisted evidence accepts only its immutable ID.")


@dataclass(frozen=True, slots=True)
class AssistantEvidenceRecord:
    """Immutable prompt-safe evidence with canonical provenance."""

    source: AssistantEvidenceSource
    reference: str
    label: str
    cutoff_at: datetime
    policy_version: str
    reliability: AssistantReliability
    payload: Mapping[str, object] = field(repr=False)
    evidence_id: str = field(init=False)

    def __post_init__(self) -> None:
        source = AssistantEvidenceSource(self.source)
        reliability = AssistantReliability(self.reliability)
        reference = self.reference.strip()
        label = self.label.strip()
        if not reference or len(reference) > MAX_SOURCE_REFERENCE_CHARACTERS:
            raise ValueError("Evidence reference must be bounded and non-empty.")
        if not label or len(label) > MAX_CITATION_LABEL_CHARACTERS:
            raise ValueError("Evidence label must be bounded and non-empty.")
        if self.cutoff_at.tzinfo is None or self.cutoff_at.utcoffset() is None:
            raise ValueError("Evidence cutoff must be timezone-aware.")
        if not self.policy_version.strip():
            raise ValueError("Evidence policy version is required.")
        if reliability is AssistantReliability.UNAVAILABLE:
            raise ValueError("Unavailable evidence cannot become a record.")
        normalized = prompt_safe_payload(source, self.payload)
        frozen = _freeze(normalized)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "reliability", reliability)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "payload", frozen)
        object.__setattr__(
            self,
            "evidence_id",
            _sha256(
                {
                    "source": source.value,
                    "reference": reference,
                    "label": label,
                    "cutoff_at": self.cutoff_at,
                    "policy_version": self.policy_version,
                    "reliability": reliability.value,
                    "payload": frozen,
                }
            ),
        )


class AssistantEvidenceAdapter(Protocol):
    """Retrieve one authorized source without exposing persistence to a model."""

    source: AssistantEvidenceSource

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        user_id: UUID | None,
        intent: AssistantIntent,
        query: AssistantEvidenceQuery,
    ) -> tuple[AssistantEvidenceRecord, ...]: ...


class AssistantEvidenceRegistry:
    """Authorize then dispatch bounded evidence queries to closed adapters."""

    def __init__(self, adapters: Sequence[AssistantEvidenceAdapter]) -> None:
        resolved = tuple(adapters)
        sources = tuple(AssistantEvidenceSource(item.source) for item in resolved)
        if len(set(sources)) != len(sources):
            raise ValueError("Assistant evidence adapters must have unique sources.")
        self._adapters = MappingProxyType(dict(zip(sources, resolved, strict=True)))

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        user_id: UUID | None,
        intent: AssistantIntent,
        queries: tuple[AssistantEvidenceQuery, ...],
    ) -> tuple[AssistantEvidenceRecord, ...]:
        if not queries or len(queries) > MAX_EVIDENCE_REQUESTS:
            raise ValueError("Evidence requests must be non-empty and bounded.")
        sources = tuple(item.source for item in queries)
        authorize_evidence_sources(
            intent=AssistantIntent(intent),
            sources=sources,
            user_id=user_id,
        )
        records: list[AssistantEvidenceRecord] = []
        for query in queries:
            adapter = self._adapters.get(query.source)
            if adapter is None:
                raise ValueError("No adapter is registered for an authorized source.")
            retrieved = await adapter.retrieve(
                session,
                user_id=user_id,
                intent=AssistantIntent(intent),
                query=query,
            )
            if any(item.source is not query.source for item in retrieved):
                raise ValueError("Evidence adapter returned the wrong source family.")
            records.extend(retrieved)
            if len(records) > MAX_EVIDENCE_RECORDS:
                raise ValueError("Retrieved evidence exceeds the record limit.")
        identifiers = tuple(item.evidence_id for item in records)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Retrieved evidence records must be unique.")
        return tuple(records)


class AnalyticsEvidenceAdapter:
    """Convert a live owner-scoped dashboard calculation into safe evidence."""

    source = AssistantEvidenceSource.ANALYTICS

    def __init__(self, service: FinancialAnalyticsService | None = None) -> None:
        self._service = service or FinancialAnalyticsService()

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        user_id: UUID | None,
        intent: AssistantIntent,
        query: AssistantEvidenceQuery,
    ) -> tuple[AssistantEvidenceRecord, ...]:
        del intent
        owner = _require_owner(user_id)
        response = await self._service.dashboard_export(
            session,
            user_id=owner,
            trusted_timezone=_required(query.trusted_timezone),
            default_currency=_required(query.currency),
            selection=AnalyticsSelection(
                date_from=query.date_from,
                date_to=query.date_to,
                currency=query.currency,
                comparison=AnalyticsComparisonMode.NONE,
            ),
            granularity=AnalyticsGranularity.MONTH,
            limit=min(query.limit, 25),
        )
        context = response.context
        confidence = context.completeness.data_confidence
        reliability = (
            AssistantReliability.NORMAL
            if confidence is AnalyticsConfidenceLevel.HIGH
            else AssistantReliability.PROVISIONAL
        )
        warnings = () if confidence is AnalyticsConfidenceLevel.HIGH else ("evidence_incomplete",)
        payload = {
            "snapshot_id": _sha256(response.model_dump(mode="json")),
            "cutoff_at": context.freshness.calculated_at,
            "period_start": context.period.date_from,
            "period_end": context.period.date_to,
            "currency": context.currency,
            "cash_flow": {
                "gross_income": response.metrics.gross_income.value,
                "total_expense": response.metrics.total_expense.value,
                "net_cash_flow": response.metrics.net_cash_flow.value,
                "savings_amount": response.metrics.savings_amount.value,
                "savings_rate": response.metrics.savings_rate.value,
            },
            "spending_summary": {
                "categories": tuple(
                    {
                        "name": item.name,
                        "amount": item.amount.value,
                        "share": item.share.value,
                        "transaction_count": item.transaction_count,
                    }
                    for item in response.spending.categories
                ),
                "merchants": tuple(
                    {
                        "name": item.display_name,
                        "amount": item.amount.value,
                        "share": item.share.value,
                        "transaction_count": item.transaction_count,
                    }
                    for item in response.spending.merchants
                ),
            },
            "warnings": warnings,
            "policy_versions": {"analytics": context.contract_version},
            "reliability": reliability.value,
        }
        return (
            AssistantEvidenceRecord(
                source=self.source,
                reference=(
                    f"dashboard:{context.period.date_from.isoformat()}:"
                    f"{context.period.date_to.isoformat()}:{context.currency}"
                ),
                label="Financial analytics dashboard",
                cutoff_at=context.freshness.calculated_at,
                policy_version=ASSISTANT_EVIDENCE_POLICY_VERSION,
                reliability=reliability,
                payload=payload,
            ),
        )


class ForecastEvidenceAdapter:
    """Retrieve one immutable owner-scoped Phase 9 forecast."""

    source = AssistantEvidenceSource.FORECAST

    def __init__(self, repository: ForecastPersistenceRepository | None = None) -> None:
        self._repository = repository or ForecastPersistenceRepository()

    async def retrieve(self, session: AsyncSession, *, user_id: UUID | None, intent: AssistantIntent, query: AssistantEvidenceQuery) -> tuple[AssistantEvidenceRecord, ...]:
        del intent
        run = await self._repository.get(session, user_id=_require_owner(user_id), run_id=_required_id(query.reference_id))
        if run is None:
            return ()
        reliability = _reliability(run.uncertainty_reliability)
        payload = {
            "run_id": run.id,
            "cutoff_at": run.data_cutoff_at,
            "target": run.target,
            "currency": run.currency,
            "horizon_start": run.forecast_start,
            "horizon_end": run.forecast_end,
            "points": tuple({"period_start": point.period_start, "expected_value": point.expected_value} for point in run.points),
            "confidence_bands": tuple({"period_start": point.period_start, "lower_80": point.lower_80, "upper_80": point.upper_80, "lower_95": point.lower_95, "upper_95": point.upper_95} for point in run.points),
            "model_name": run.model_code,
            "model_version": run.model_version,
            "quality": {"selection_metric": run.selection_metric, "validation_mae": run.validation_mae, "validation_rmse": run.validation_rmse, "validation_wape": run.validation_wape},
            "warnings": () if reliability is AssistantReliability.NORMAL else ("evidence_provisional",),
            "policy_versions": {"contract": run.contract_version, "quality": run.quality_policy_version, "evaluation": run.evaluation_policy_version, "selection": run.selection_policy_version, "uncertainty": run.uncertainty_policy_version},
            "reliability": reliability.value,
        }
        return (AssistantEvidenceRecord(source=self.source, reference=str(run.id), label=f"{run.target.replace('_', ' ').title()} forecast", cutoff_at=run.data_cutoff_at, policy_version=ASSISTANT_EVIDENCE_POLICY_VERSION, reliability=reliability, payload=payload),)


class GoalProgressEvidenceAdapter:
    """Calculate current goal progress through the existing owner-scoped service."""

    source = AssistantEvidenceSource.GOAL_PROGRESS

    def __init__(self, service: ContributionService | None = None, clock: Clock | None = None) -> None:
        self._service = service or ContributionService()
        self._clock = clock or SystemClock()

    async def retrieve(self, session: AsyncSession, *, user_id: UUID | None, intent: AssistantIntent, query: AssistantEvidenceQuery) -> tuple[AssistantEvidenceRecord, ...]:
        del intent
        progress = await self._service.progress(session, user_id=_require_owner(user_id), goal_id=_required_id(query.reference_id), trusted_timezone=_required(query.trusted_timezone))
        cutoff = self._clock.now()
        payload = {
            "goal_id": progress.goal_id,
            "name": progress.goal_name,
            "currency": progress.currency,
            "target_amount": progress.target_amount,
            "current_amount": progress.current_amount,
            "remaining_amount": progress.remaining_amount,
            "progress_percent": progress.funding_percentage,
            "target_date": progress.target_date,
            "required_monthly_contribution": progress.required_monthly_contribution,
            "status": progress.funding_state.value,
            "warnings": (),
            "cutoff_at": cutoff,
            "policy_versions": {"goal_planning": GOAL_PLANNING_CONTRACT_VERSION},
        }
        return (AssistantEvidenceRecord(source=self.source, reference=str(progress.goal_id), label=f"Goal progress: {progress.goal_name}", cutoff_at=cutoff, policy_version=ASSISTANT_EVIDENCE_POLICY_VERSION, reliability=AssistantReliability.NORMAL, payload=payload),)


class GoalPlanEvidenceAdapter:
    """Retrieve one immutable Phase 10 plan and bounded schedule summary."""

    source = AssistantEvidenceSource.GOAL_PLAN

    def __init__(self, repository: GoalPlanRepository | None = None) -> None:
        self._repository = repository or GoalPlanRepository()

    async def retrieve(self, session: AsyncSession, *, user_id: UUID | None, intent: AssistantIntent, query: AssistantEvidenceQuery) -> tuple[AssistantEvidenceRecord, ...]:
        del intent
        run = await self._repository.get(session, user_id=_require_owner(user_id), plan_id=_required_id(query.reference_id))
        if run is None:
            return ()
        reliability = _reliability(run.forecast_reliability)
        payload = {
            "run_id": run.id,
            "cutoff_at": run.planning_cutoff_at,
            "currency": run.currency,
            "status": run.status.value,
            "goals": tuple({"name": item.goal_name, "type": item.goal_type, "priority": item.priority, "target_date": item.target_date, "target_amount": item.target_amount, "current_amount": item.current_amount, "rank": item.rank, "allocated_amount": item.allocated_amount, "projected_remaining_amount": item.projected_remaining_amount, "completion_probability": item.completion_probability, "deadline_met": item.deadline_met, "reliability": item.evidence_reliability} for item in run.outcomes),
            "periods": tuple({"period_start": item.period_start, "available_capacity": item.available_capacity, "allocated_amount": item.allocated_amount, "unallocated_amount": item.unallocated_amount} for item in run.periods),
            "allocations": tuple({"period_start": period.period_start, "items": tuple({"rank": item.rank, "amount": item.amount, "cumulative_amount": item.cumulative_amount, "projected_remaining_amount": item.projected_remaining_amount} for item in period.allocations)} for period in run.periods),
            "probabilities": tuple({"goal_name": item.goal_name, "completion_probability": item.completion_probability} for item in run.outcomes),
            "shortfalls": tuple({"goal_name": item.goal_name, "protected_shortfall": item.protected_shortfall, "expected_shortfall": item.expected_shortfall, "projected_remaining_amount": item.projected_remaining_amount} for item in run.outcomes),
            "safety_reservations": {"emergency_reserve_amount": run.emergency_reserve_amount, "guardrail_reason_codes": tuple(run.guardrail_reason_codes)},
            "reliability": reliability.value,
            "reason_codes": tuple(run.reason_codes),
            "policy_versions": {"contract": run.contract_version, "plan": run.plan_policy_version, "feasibility": run.feasibility_policy_version, "ranking": run.ranking_policy_version, "optimization": run.optimization_policy_version, "guardrail": run.guardrail_policy_version},
        }
        return (AssistantEvidenceRecord(source=self.source, reference=str(run.id), label="Goal optimization plan", cutoff_at=run.planning_cutoff_at, policy_version=ASSISTANT_EVIDENCE_POLICY_VERSION, reliability=reliability, payload=payload),)


class ScenarioEvidenceAdapter:
    """Retrieve one immutable Phase 11 scenario decision graph."""

    source = AssistantEvidenceSource.SCENARIO_SIMULATION

    def __init__(self, repository: ScenarioSimulationRepository | None = None) -> None:
        self._repository = repository or ScenarioSimulationRepository()

    async def retrieve(self, session: AsyncSession, *, user_id: UUID | None, intent: AssistantIntent, query: AssistantEvidenceQuery) -> tuple[AssistantEvidenceRecord, ...]:
        del intent
        run = await self._repository.get(session, user_id=_require_owner(user_id), run_id=_required_id(query.reference_id))
        if run is None:
            return ()
        reliabilities = tuple(_reliability(item.reliability) for item in run.definitions)
        reliability = _worst_reliability(reliabilities)
        recommended = next((item.scenario_definition_id for item in run.comparisons if item.recommended), None)
        payload = {
            "run_id": run.id,
            "cutoff_at": run.cutoff_at,
            "currency": run.currency,
            "definitions": tuple({"name": item.name, "kind": item.kind, "evaluation_status": item.evaluation_status, "risk_status": item.risk_status, "reliability": item.reliability, "capacity_total": item.capacity_total, "allocated_total": item.allocated_total, "unallocated_total": item.unallocated_total, "robustness_score": item.robustness_score} for item in run.definitions),
            "comparisons": tuple({"rank": item.rank, "recommended": item.recommended, "decision_score": item.decision_score, "expected_capacity_delta": item.expected_capacity_delta, "completion_probability_delta": item.completion_probability_delta, "deadline_probability_delta": item.deadline_probability_delta, "expected_shortfall_delta": item.expected_shortfall_delta, "tail_shortfall_delta": item.tail_shortfall_delta, "reason_codes": tuple(item.reason_codes)} for item in run.comparisons),
            "probabilities": tuple({"name": item.name, "all_goals_completion": item.all_goals_completion_probability, "all_deadlines_met": item.all_deadlines_met_probability, "reserve_coverage": item.reserve_coverage_probability, "negative_savings": item.negative_savings_probability, "constraint_feasibility": item.constraint_feasibility_probability} for item in run.definitions),
            "percentiles": (),
            "tail_risk": tuple({"name": item.name, "tail_expected_shortfall_90": item.tail_expected_shortfall_90} for item in run.definitions),
            "sensitivity": tuple({"rank": item.rank, "signals": tuple(item.sensitivity_signals)} for item in run.comparisons),
            "ranks": tuple({"rank": item.rank, "recommended": item.recommended, "score": item.decision_score} for item in run.comparisons),
            "recommendation": str(recommended) if recommended is not None else None,
            "warnings": tuple(run.snapshot_warnings),
            "policy_versions": {"contract": run.contract_version, "comparison": run.comparison_policy_version, "sensitivity": run.sensitivity_policy_version, "decision": run.decision_policy_version, "risk": run.risk_policy_version},
        }
        return (AssistantEvidenceRecord(source=self.source, reference=str(run.id), label="Scenario comparison", cutoff_at=run.cutoff_at, policy_version=ASSISTANT_EVIDENCE_POLICY_VERSION, reliability=reliability, payload=payload),)


def structured_evidence_adapters() -> tuple[AssistantEvidenceAdapter, ...]:
    """Return the five private adapters; curated knowledge is registered separately."""

    return (
        AnalyticsEvidenceAdapter(),
        ForecastEvidenceAdapter(),
        GoalProgressEvidenceAdapter(),
        GoalPlanEvidenceAdapter(),
        ScenarioEvidenceAdapter(),
    )


def _require_owner(user_id: UUID | None) -> UUID:
    if user_id is None:
        raise PermissionError("Private evidence requires the authenticated owner.")
    return user_id


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("Required evidence context is missing.")
    return value


def _required_id(value: UUID | None) -> UUID:
    if value is None:
        raise ValueError("Required evidence resource is missing.")
    return value


def _reliability(value: object) -> AssistantReliability:
    normalized = str(getattr(value, "value", value)).casefold()
    if normalized == "normal":
        return AssistantReliability.NORMAL
    if normalized == "provisional":
        return AssistantReliability.PROVISIONAL
    if normalized == "conservative":
        return AssistantReliability.CONSERVATIVE
    return AssistantReliability.CONSERVATIVE


def _worst_reliability(values: tuple[AssistantReliability, ...]) -> AssistantReliability:
    order = {AssistantReliability.NORMAL: 0, AssistantReliability.PROVISIONAL: 1, AssistantReliability.CONSERVATIVE: 2, AssistantReliability.UNAVAILABLE: 3}
    return max(values, key=order.__getitem__) if values else AssistantReliability.CONSERVATIVE


def _freeze(value: object) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _sha256(value: object) -> str:
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


__all__ = [
    "AnalyticsEvidenceAdapter",
    "AssistantEvidenceAdapter",
    "AssistantEvidenceQuery",
    "AssistantEvidenceRecord",
    "AssistantEvidenceRegistry",
    "ForecastEvidenceAdapter",
    "GoalPlanEvidenceAdapter",
    "GoalProgressEvidenceAdapter",
    "ScenarioEvidenceAdapter",
    "structured_evidence_adapters",
]
