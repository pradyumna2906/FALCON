"""Atomic end-to-end orchestration for owner-scoped grounded answers."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic, perf_counter
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.assistant.evidence import (
    AssistantEvidenceQuery,
    AssistantEvidenceRegistry,
)
from falcon_api.assistant.grounding import (
    AssistantGroundingError,
    GroundedAssistantGenerator,
    GroundedAssistantResult,
)
from falcon_api.assistant.history import (
    AssistantHistoryCapacityError,
    AssistantHistoryService,
    AssistantHistoryTurn,
    AssistantIdempotencyConflict,
)
from falcon_api.assistant.model import (
    AssistantModelBudgetError,
    AssistantModelOutputError,
    AssistantModelTimeoutError,
    AssistantModelUnavailableError,
)
from falcon_api.assistant.monitoring import (
    AssistantFailureReason,
    AssistantMonitor,
    AssistantProviderOutcome,
)
from falcon_api.assistant.packet import build_evidence_packet
from falcon_api.assistant.safety import screen_question
from falcon_api.assistant.semantics import (
    MAX_KNOWLEDGE_QUERY_CHARACTERS,
    MAX_QUESTION_CHARACTERS,
    AssistantAnswerStatus,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantKnowledgeTopic,
)
from falcon_api.assistant.verification import AssistantVerificationError
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.forecasting.persistence import ForecastPersistenceRepository
from falcon_api.goal_planning.persistence import GoalPlanRepository
from falcon_api.goal_planning.repository import GoalRepository
from falcon_api.scenario_simulation.persistence import (
    ScenarioSimulationRepository,
)


MAX_TRACKED_RATE_LIMIT_OWNERS = 10_000
_NIL_ID = UUID(int=0)
_NORMALIZE_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class AssistantEvidencePlan:
    """Server-selected evidence query set for one resolved intent."""

    intent: AssistantIntent
    queries: tuple[AssistantEvidenceQuery, ...]

    def __post_init__(self) -> None:
        intent = AssistantIntent(self.intent)
        queries = tuple(self.queries)
        if intent is AssistantIntent.UNSUPPORTED or not queries:
            raise ValueError("Supported assistant plans require evidence queries.")
        sources = tuple(item.source for item in queries)
        if len(set(sources)) != len(sources):
            raise ValueError("Assistant plan sources must be unique.")
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "queries", queries)


@dataclass(frozen=True, slots=True)
class AssistantMessageResult:
    """One persisted exchange or exact idempotent replay."""

    turn: AssistantHistoryTurn
    replayed: bool


class AssistantEvidencePlanner(Protocol):
    """Resolve server-owned evidence resources after authentication."""

    async def plan(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        question: str,
        intent: AssistantIntent,
        trusted_timezone: str,
        default_currency: str,
    ) -> AssistantEvidencePlan: ...


class AssistantIntentClassifier:
    """Conservative deterministic classifier that cannot invoke a provider."""

    _RULES = (
        (
            AssistantIntent.COMPARE_SCENARIOS,
            re.compile(r"\b(?:scenario|what[ -]?if|alternative|best case|worst case)\b", re.I),
        ),
        (
            AssistantIntent.EXPLAIN_GOAL_PLAN,
            re.compile(r"\b(?:goal plan|allocation plan|savings plan|optimized? plan|schedule)\b", re.I),
        ),
        (
            AssistantIntent.EXPLAIN_GOAL_PROGRESS,
            re.compile(r"\bgoal\b.*\b(?:progress|on track|target|contribution|remaining)\b|\b(?:progress|on track|contribution)\b.*\bgoal\b", re.I),
        ),
        (
            AssistantIntent.EXPLAIN_FORECAST,
            re.compile(r"\b(?:forecast|projection|projected|outlook|prediction|predict)\b", re.I),
        ),
        (
            AssistantIntent.EXPLAIN_FINANCIAL_HEALTH,
            re.compile(r"\b(?:financial health|health score|financial score)\b", re.I),
        ),
        (
            AssistantIntent.EXPLAIN_SPENDING_SIGNAL,
            re.compile(r"\b(?:spending signal|spending leak|anomal(?:y|ies)|recurring charge|unusual spending)\b", re.I),
        ),
        (
            AssistantIntent.SUMMARIZE_SPENDING,
            re.compile(r"\b(?:spending|expenses?|expense categor(?:y|ies)|spent)\b", re.I),
        ),
        (
            AssistantIntent.EXPLAIN_DASHBOARD,
            re.compile(r"\b(?:dashboard|cash flow|income summary|financial summary)\b", re.I),
        ),
        (
            AssistantIntent.FINANCIAL_EDUCATION,
            re.compile(r"\b(?:budget|saving|emergency fund|debt|interest|inflation|financial|finance|money|risk|credit)\b", re.I),
        ),
    )

    def classify(self, question: str) -> AssistantIntent:
        normalized = _question(question)
        for intent, pattern in self._RULES:
            if pattern.search(normalized):
                return intent
        return AssistantIntent.UNSUPPORTED


class DeterministicAssistantEvidencePlanner:
    """Choose current owner resources and curated topics without model input."""

    def __init__(
        self,
        *,
        forecasts: ForecastPersistenceRepository | None = None,
        goals: GoalRepository | None = None,
        plans: GoalPlanRepository | None = None,
        scenarios: ScenarioSimulationRepository | None = None,
    ) -> None:
        self._forecasts = forecasts or ForecastPersistenceRepository()
        self._goals = goals or GoalRepository()
        self._plans = plans or GoalPlanRepository()
        self._scenarios = scenarios or ScenarioSimulationRepository()

    async def plan(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        question: str,
        intent: AssistantIntent,
        trusted_timezone: str,
        default_currency: str,
    ) -> AssistantEvidencePlan:
        resolved = AssistantIntent(intent)
        knowledge = AssistantEvidenceQuery(
            source=AssistantEvidenceSource.KNOWLEDGE,
            text=_knowledge_query(question),
            topics=_topics(resolved, question),
            limit=3,
        )
        analytics = AssistantEvidenceQuery(
            source=AssistantEvidenceSource.ANALYTICS,
            trusted_timezone=trusted_timezone,
            currency=default_currency,
            limit=6,
        )
        if resolved in {
            AssistantIntent.EXPLAIN_DASHBOARD,
            AssistantIntent.EXPLAIN_FINANCIAL_HEALTH,
            AssistantIntent.SUMMARIZE_SPENDING,
            AssistantIntent.EXPLAIN_SPENDING_SIGNAL,
        }:
            queries = (analytics, knowledge)
        elif resolved is AssistantIntent.EXPLAIN_FORECAST:
            forecast = await self._latest_forecast(session, user_id=user_id)
            queries = (_resource(AssistantEvidenceSource.FORECAST, forecast), knowledge)
        elif resolved is AssistantIntent.EXPLAIN_GOAL_PROGRESS:
            goals = await self._goals.list(
                session,
                user_id=user_id,
                status=None,
                limit=100,
            )
            goal_id = _select_goal_id(goals, question)
            queries = (
                AssistantEvidenceQuery(
                    source=AssistantEvidenceSource.GOAL_PROGRESS,
                    reference_id=goal_id,
                    trusted_timezone=trusted_timezone,
                    limit=1,
                ),
                knowledge,
            )
        elif resolved is AssistantIntent.EXPLAIN_GOAL_PLAN:
            plans = await self._plans.list_recent(
                session,
                user_id=user_id,
                limit=1,
            )
            plan = plans[0] if plans else None
            queries = (
                _resource(
                    AssistantEvidenceSource.GOAL_PLAN,
                    plan.id if plan is not None else None,
                ),
                _resource(
                    AssistantEvidenceSource.FORECAST,
                    plan.forecast_run_id if plan is not None else None,
                ),
                knowledge,
            )
        elif resolved is AssistantIntent.COMPARE_SCENARIOS:
            runs = await self._scenarios.list_recent(
                session,
                user_id=user_id,
                limit=1,
            )
            run = runs[0] if runs else None
            plan = (
                await self._plans.get(
                    session,
                    user_id=user_id,
                    plan_id=run.source_plan_id,
                )
                if run is not None
                else None
            )
            queries = (
                _resource(
                    AssistantEvidenceSource.SCENARIO_SIMULATION,
                    run.id if run is not None else None,
                ),
                _resource(
                    AssistantEvidenceSource.GOAL_PLAN,
                    run.source_plan_id if run is not None else None,
                ),
                _resource(
                    AssistantEvidenceSource.FORECAST,
                    plan.forecast_run_id if plan is not None else None,
                ),
                knowledge,
            )
        elif resolved is AssistantIntent.FINANCIAL_EDUCATION:
            queries = (knowledge,)
        else:
            raise ValueError("Unsupported intents cannot select evidence.")
        return AssistantEvidencePlan(intent=resolved, queries=queries)

    async def _latest_forecast(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> UUID:
        runs = await self._forecasts.list_recent(
            session,
            user_id=user_id,
            limit=1,
        )
        return runs[0].id if runs else _NIL_ID


class AssistantRequestLimiter:
    """Bound process-local rate and concurrency; Phase 13 distributes it."""

    def __init__(
        self,
        *,
        requests_per_minute: int,
        max_concurrent_requests: int,
        timer: Callable[[], float] = monotonic,
    ) -> None:
        if not 1 <= requests_per_minute <= 60:
            raise ValueError("Assistant request rate is outside policy.")
        if not 1 <= max_concurrent_requests <= 4:
            raise ValueError("Assistant concurrency is outside policy.")
        self._rate = requests_per_minute
        self._concurrency = max_concurrent_requests
        self._timer = timer
        self._guard = asyncio.Lock()
        self._events: dict[str, deque[float]] = {}
        self._inflight: dict[str, int] = {}

    @asynccontextmanager
    async def permit(self, user_id: UUID) -> AsyncIterator[None]:
        key = hashlib.sha256(user_id.bytes).hexdigest()
        async with self._guard:
            now = self._timer()
            events = self._events.get(key)
            if events is None:
                self._reserve_owner(now)
                events = self._events.setdefault(key, deque())
            while events and events[0] <= now - 60:
                events.popleft()
            if self._inflight.get(key, 0) >= self._concurrency:
                raise ApplicationError(
                    code="assistant_busy",
                    message="The assistant is already processing a request.",
                    status_code=429,
                )
            if len(events) >= self._rate:
                raise ApplicationError(
                    code="assistant_rate_limited",
                    message="The assistant request limit was reached.",
                    status_code=429,
                )
            events.append(now)
            self._inflight[key] = self._inflight.get(key, 0) + 1
        try:
            yield
        finally:
            async with self._guard:
                remaining = self._inflight.get(key, 1) - 1
                if remaining:
                    self._inflight[key] = remaining
                else:
                    self._inflight.pop(key, None)

    def _reserve_owner(self, now: float) -> None:
        if len(self._events) < MAX_TRACKED_RATE_LIMIT_OWNERS:
            return
        for candidate, events in tuple(self._events.items()):
            if candidate in self._inflight:
                continue
            while events and events[0] <= now - 60:
                events.popleft()
            if not events:
                self._events.pop(candidate, None)
                return
        raise ApplicationError(
            code="assistant_capacity_unavailable",
            message="Assistant capacity is temporarily unavailable.",
            status_code=429,
        )


class GroundedAssistantOrchestrator:
    """Classify, authorize, retrieve, generate, verify, persist, and return."""

    def __init__(
        self,
        *,
        registry: AssistantEvidenceRegistry,
        generator: GroundedAssistantGenerator,
        history: AssistantHistoryService,
        planner: AssistantEvidencePlanner | None = None,
        classifier: AssistantIntentClassifier | None = None,
        limiter: AssistantRequestLimiter,
        monitor: AssistantMonitor | None = None,
        clock: Clock | None = None,
        timeout_seconds: float = 30.0,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 60:
            raise ValueError("Assistant request timeout is outside policy.")
        self._registry = registry
        self._generator = generator
        self._history = history
        self._planner = planner or DeterministicAssistantEvidencePlanner()
        self._classifier = classifier or AssistantIntentClassifier()
        self._limiter = limiter
        self._monitor = monitor or AssistantMonitor()
        self._clock = clock or SystemClock()
        self._timeout = timeout_seconds
        self._timer = timer

    async def send_message(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        question: str,
        idempotency_key: str,
        trusted_timezone: str,
        default_currency: str,
    ) -> AssistantMessageResult:
        normalized_question = _question(question)
        started_at = self._timer()
        intent = AssistantIntent.UNSUPPORTED
        sources: tuple[AssistantEvidenceSource, ...] = ()
        evidence_count = 0
        try:
            async with self._limiter.permit(user_id):
                async with asyncio.timeout(self._timeout):
                    exists, previous = await self._history.lock_and_find(
                        session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        idempotency_key=idempotency_key,
                    )
                    if not exists:
                        raise _error(
                            "assistant_conversation_not_found",
                            "The requested assistant conversation was not found.",
                            404,
                        )
                    if previous is not None:
                        if previous.question != normalized_question:
                            raise _error(
                                "assistant_idempotency_conflict",
                                "The idempotency key was already used for another message.",
                                409,
                            )
                        self._record_completion(
                            started_at=started_at,
                            intent=previous.answer.intent,
                            sources=(),
                            evidence_count=0,
                            result=None,
                            replay=previous,
                        )
                        return AssistantMessageResult(previous, True)

                    intent = self._classifier.classify(normalized_question)
                    denied = screen_question(normalized_question, intent=intent)
                    if denied is not None:
                        result = GroundedAssistantResult(
                            answer=denied,
                            packet_id=None,
                            used_evidence_ids=(),
                            model_result=None,
                            verified=True,
                        )
                    else:
                        plan = await self._planner.plan(
                            session,
                            user_id=user_id,
                            question=normalized_question,
                            intent=intent,
                            trusted_timezone=trusted_timezone,
                            default_currency=default_currency,
                        )
                        sources = tuple(item.source for item in plan.queries)
                        evidence = await self._registry.retrieve(
                            session,
                            user_id=user_id,
                            intent=intent,
                            queries=plan.queries,
                        )
                        evidence_count = len(evidence)
                        packet = build_evidence_packet(
                            question=normalized_question,
                            intent=intent,
                            user_id=user_id,
                            requested_sources=sources,
                            evidence=evidence,
                            created_at=self._clock.now(),
                        )
                        result = await self._generator.generate(packet)

                    latency_ms = _elapsed_ms(self._timer(), started_at)
                    turn = await self._history.append(
                        session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        question=normalized_question,
                        result=result,
                        latency_ms=latency_ms,
                        idempotency_key=idempotency_key,
                    )
                    if turn is None:
                        raise _error(
                            "assistant_conversation_not_found",
                            "The requested assistant conversation was not found.",
                            404,
                        )
                    self._record_completion(
                        started_at=started_at,
                        intent=intent,
                        sources=sources,
                        evidence_count=evidence_count,
                        result=result,
                        replay=None,
                    )
                    return AssistantMessageResult(turn, False)
        except AssistantHistoryCapacityError:
            self._record_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.NOT_CALLED,
                AssistantFailureReason.HISTORY_LIMIT,
            )
            raise _error(
                "assistant_conversation_full",
                "The assistant conversation has reached its message limit.",
                409,
            ) from None
        except AssistantIdempotencyConflict:
            self._record_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.NOT_CALLED,
                AssistantFailureReason.IDEMPOTENCY_CONFLICT,
            )
            raise _error(
                "assistant_idempotency_conflict",
                "The idempotency key was already used for another message.",
                409,
            ) from None
        except AssistantModelTimeoutError:
            self._provider_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.TIMED_OUT,
                AssistantFailureReason.REQUEST_TIMEOUT,
            )
            raise _error(
                "assistant_timeout",
                "The assistant could not complete the request in time.",
                503,
            ) from None
        except AssistantModelUnavailableError:
            self._provider_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.UNAVAILABLE,
                AssistantFailureReason.PROVIDER_UNAVAILABLE,
            )
            raise _error(
                "assistant_unavailable",
                "The assistant is temporarily unavailable.",
                503,
            ) from None
        except AssistantModelBudgetError:
            self._provider_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.OVER_BUDGET,
                AssistantFailureReason.PROVIDER_INVALID,
            )
            raise _error(
                "assistant_response_rejected",
                "The assistant response did not pass release checks.",
                503,
            ) from None
        except AssistantModelOutputError:
            self._provider_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.MALFORMED,
                AssistantFailureReason.PROVIDER_INVALID,
            )
            raise _error(
                "assistant_response_rejected",
                "The assistant response did not pass release checks.",
                503,
            ) from None
        except (AssistantVerificationError, AssistantGroundingError):
            self._provider_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.VERIFICATION_BLOCKED,
                AssistantFailureReason.PROVIDER_INVALID,
            )
            raise _error(
                "assistant_response_rejected",
                "The assistant response did not pass release checks.",
                503,
            ) from None
        except TimeoutError:
            self._provider_failure(
                started_at,
                intent,
                sources,
                evidence_count,
                AssistantProviderOutcome.TIMED_OUT,
                AssistantFailureReason.REQUEST_TIMEOUT,
            )
            raise _error(
                "assistant_timeout",
                "The assistant could not complete the request in time.",
                503,
            ) from None
        except ApplicationError as exc:
            reason = {
                "assistant_conversation_not_found": AssistantFailureReason.NOT_FOUND,
                "assistant_rate_limited": AssistantFailureReason.RATE_LIMITED,
                "assistant_busy": AssistantFailureReason.CONCURRENCY_LIMITED,
                "assistant_idempotency_conflict": AssistantFailureReason.IDEMPOTENCY_CONFLICT,
            }.get(exc.code)
            if reason is not None:
                self._record_failure(
                    started_at,
                    intent,
                    sources,
                    evidence_count,
                    AssistantProviderOutcome.NOT_CALLED,
                    reason,
                )
            raise

    def _record_completion(
        self,
        *,
        started_at: float,
        intent: AssistantIntent,
        sources: tuple[AssistantEvidenceSource, ...],
        evidence_count: int,
        result: GroundedAssistantResult | None,
        replay: AssistantHistoryTurn | None,
    ) -> None:
        if replay is not None:
            answer = replay.answer
        elif result is not None:
            answer = result.answer
        else:
            raise ValueError("Assistant completion telemetry requires a result.")
        model_result = result.model_result if result is not None else None
        usage = model_result.usage if model_result is not None else None
        provider_outcome = (
            AssistantProviderOutcome.REPLAYED
            if replay is not None
            else (
                AssistantProviderOutcome.SUCCEEDED
                if model_result is not None
                else AssistantProviderOutcome.NOT_CALLED
            )
        )
        self._monitor.record_completion(
            intent=intent,
            sources=sources,
            evidence_count=evidence_count,
            status=answer.status,
            refusal_reason=answer.refusal_reason,
            citation_count=len(answer.citations),
            input_tokens=usage.input_tokens if usage is not None else 0,
            output_tokens=usage.output_tokens if usage is not None else 0,
            latency_ms=_elapsed_ms(self._timer(), started_at),
            provider_outcome=provider_outcome,
        )

    def _provider_failure(
        self,
        started_at: float,
        intent: AssistantIntent,
        sources: tuple[AssistantEvidenceSource, ...],
        evidence_count: int,
        outcome: AssistantProviderOutcome,
        reason: AssistantFailureReason,
    ) -> None:
        self._record_failure(
            started_at,
            intent,
            sources,
            evidence_count,
            outcome,
            reason,
        )

    def _record_failure(
        self,
        started_at: float,
        intent: AssistantIntent,
        sources: tuple[AssistantEvidenceSource, ...],
        evidence_count: int,
        outcome: AssistantProviderOutcome,
        reason: AssistantFailureReason,
    ) -> None:
        self._monitor.record_failure(
            intent=intent,
            sources=sources,
            evidence_count=evidence_count,
            latency_ms=_elapsed_ms(self._timer(), started_at),
            provider_outcome=outcome,
            reason=reason,
        )


def _resource(
    source: AssistantEvidenceSource,
    reference_id: UUID | None,
) -> AssistantEvidenceQuery:
    return AssistantEvidenceQuery(
        source=source,
        reference_id=reference_id or _NIL_ID,
        limit=1,
    )


def _select_goal_id(goals: tuple[object, ...], question: str) -> UUID:
    folded = question.casefold()
    for goal in goals:
        name = str(getattr(goal, "name", "")).strip().casefold()
        if name and name in folded:
            return getattr(goal, "id")
    return getattr(goals[0], "id") if goals else _NIL_ID


def _topics(
    intent: AssistantIntent,
    question: str,
) -> tuple[AssistantKnowledgeTopic, ...]:
    fixed = {
        AssistantIntent.EXPLAIN_DASHBOARD: (
            AssistantKnowledgeTopic.CASH_FLOW,
            AssistantKnowledgeTopic.BUDGETING,
        ),
        AssistantIntent.EXPLAIN_FINANCIAL_HEALTH: (
            AssistantKnowledgeTopic.FINANCIAL_LITERACY,
            AssistantKnowledgeTopic.FINANCIAL_RISK,
        ),
        AssistantIntent.SUMMARIZE_SPENDING: (
            AssistantKnowledgeTopic.BUDGETING,
            AssistantKnowledgeTopic.CASH_FLOW,
        ),
        AssistantIntent.EXPLAIN_SPENDING_SIGNAL: (
            AssistantKnowledgeTopic.BUDGETING,
        ),
        AssistantIntent.EXPLAIN_FORECAST: (
            AssistantKnowledgeTopic.FORECASTING,
        ),
        AssistantIntent.EXPLAIN_GOAL_PROGRESS: (
            AssistantKnowledgeTopic.GOAL_PLANNING,
            AssistantKnowledgeTopic.SAVINGS,
        ),
        AssistantIntent.EXPLAIN_GOAL_PLAN: (
            AssistantKnowledgeTopic.GOAL_PLANNING,
            AssistantKnowledgeTopic.FORECASTING,
        ),
        AssistantIntent.COMPARE_SCENARIOS: (
            AssistantKnowledgeTopic.SCENARIO_PLANNING,
            AssistantKnowledgeTopic.FINANCIAL_RISK,
        ),
    }
    if intent in fixed:
        return fixed[intent]
    folded = question.casefold()
    inferred = tuple(
        topic
        for token, topic in (
            ("budget", AssistantKnowledgeTopic.BUDGETING),
            ("cash flow", AssistantKnowledgeTopic.CASH_FLOW),
            ("saving", AssistantKnowledgeTopic.SAVINGS),
            ("emergency", AssistantKnowledgeTopic.EMERGENCY_FUNDS),
            ("debt", AssistantKnowledgeTopic.DEBT),
            ("forecast", AssistantKnowledgeTopic.FORECASTING),
            ("goal", AssistantKnowledgeTopic.GOAL_PLANNING),
            ("scenario", AssistantKnowledgeTopic.SCENARIO_PLANNING),
            ("risk", AssistantKnowledgeTopic.FINANCIAL_RISK),
        )
        if token in folded
    )
    return inferred or (AssistantKnowledgeTopic.FINANCIAL_LITERACY,)


def _knowledge_query(question: str) -> str:
    normalized = _question(question)
    if len(normalized) <= MAX_KNOWLEDGE_QUERY_CHARACTERS:
        return normalized
    bounded = normalized[:MAX_KNOWLEDGE_QUERY_CHARACTERS]
    return bounded.rsplit(" ", 1)[0] or bounded


def _question(value: str) -> str:
    normalized = _NORMALIZE_SPACE.sub(" ", value).strip()
    if not normalized or len(normalized) > MAX_QUESTION_CHARACTERS:
        raise ValueError("Assistant question must be non-empty and bounded.")
    return normalized


def _elapsed_ms(finished_at: float, started_at: float) -> int:
    return min(60_000, max(0, round((finished_at - started_at) * 1_000)))


def _error(code: str, message: str, status_code: int) -> ApplicationError:
    return ApplicationError(code=code, message=message, status_code=status_code)


__all__ = [
    "AssistantEvidencePlan",
    "AssistantEvidencePlanner",
    "AssistantIntentClassifier",
    "AssistantMessageResult",
    "AssistantRequestLimiter",
    "DeterministicAssistantEvidencePlanner",
    "GroundedAssistantOrchestrator",
]
