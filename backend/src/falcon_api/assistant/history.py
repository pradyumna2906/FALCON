"""Private, bounded conversation history and content-free assistant audit trail."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.assistant.contracts import AssistantAnswer, AssistantCitation
from falcon_api.assistant.grounding import GroundedAssistantResult
from falcon_api.assistant.semantics import (
    ASSISTANT_GENERATION_POLICY_VERSION,
    MAX_QUESTION_CHARACTERS,
    AssistantAnswerStatus,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantRefusalReason,
    AssistantReliability,
    AssistantWarning,
)
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.models.assistant import (
    AssistantAuditEvent,
    AssistantConversation,
    AssistantConversationTurn,
)


RETENTION_DAYS = 90
MAX_TURNS = 50
MAX_HISTORY_PAGE = 20
_HASH = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class AssistantHistoryTurn:
    id: UUID
    ordinal: int
    question: str
    answer: AssistantAnswer
    created_at: datetime


class AssistantHistoryService:
    """Owner predicates on every operation; caller owns transaction commit."""

    def __init__(self, *, encryption_keys: tuple[bytes, ...], clock: Clock | None = None) -> None:
        if not encryption_keys or len(encryption_keys) > 3:
            raise ValueError("Assistant history requires a bounded configured key ring.")
        self._cipher = MultiFernet([Fernet(key) for key in encryption_keys])
        self._clock = clock or SystemClock()

    async def create(self, session: AsyncSession, *, user_id: UUID) -> AssistantConversation:
        _owner(user_id)
        now = self._clock.now()
        conversation = AssistantConversation(
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(days=RETENTION_DAYS),
        )
        session.add(conversation)
        await session.flush()
        return conversation

    async def append(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        question: str,
        result: GroundedAssistantResult,
        latency_ms: int,
    ) -> AssistantHistoryTurn | None:
        """Persist only a verified public answer and server-derived provenance."""

        _owner(user_id)
        normalized_question = " ".join(question.split())
        if not normalized_question or len(normalized_question) > MAX_QUESTION_CHARACTERS:
            raise ValueError("History question must be non-empty and bounded.")
        if not result.verified:
            raise ValueError("Only a verified assistant result can enter history.")
        if not isinstance(latency_ms, int) or isinstance(latency_ms, bool) or not 0 <= latency_ms <= 60_000:
            raise ValueError("Assistant latency is outside the audit budget.")
        if result.packet_id is not None and _HASH.fullmatch(result.packet_id) is None:
            raise ValueError("Invalid evidence packet identity.")
        if len(result.used_evidence_ids) > 20 or any(_HASH.fullmatch(item) is None for item in result.used_evidence_ids):
            raise ValueError("Invalid bounded evidence references.")
        generated = result.answer.status in (AssistantAnswerStatus.ANSWERED, AssistantAnswerStatus.LIMITED)
        if generated != (result.model_result is not None):
            raise ValueError("A generated answer requires a verified model result.")

        now = self._clock.now()
        conversation = await session.scalar(
            select(AssistantConversation)
            .where(
                AssistantConversation.id == conversation_id,
                AssistantConversation.user_id == user_id,
                AssistantConversation.expires_at > now,
            )
            .with_for_update()
        )
        if conversation is None:
            return None  # Foreign and nonexistent conversations are indistinguishable.
        last = await session.scalar(
            select(func.max(AssistantConversationTurn.ordinal)).where(
                AssistantConversationTurn.conversation_id == conversation_id,
                AssistantConversationTurn.user_id == user_id,
            )
        )
        ordinal = (last or 0) + 1
        if ordinal > MAX_TURNS:
            raise ValueError("Conversation has reached its turn limit.")
        usage = result.model_result.usage if result.model_result is not None else None
        answer_document = _answer_document(result.answer)
        serialized_answer = json.dumps(answer_document, ensure_ascii=True).encode("utf-8")
        if len(serialized_answer) > 30_000:
            raise ValueError("Public answer exceeds the history storage limit.")
        encrypted_question = self._cipher.encrypt(normalized_question.encode("utf-8")).decode("ascii")
        encrypted_answer = self._cipher.encrypt(serialized_answer).decode("ascii")
        turn = AssistantConversationTurn(
            user_id=user_id,
            conversation_id=conversation_id,
            ordinal=ordinal,
            question_ciphertext=encrypted_question,
            answer_ciphertext=encrypted_answer,
            packet_id=result.packet_id,
            model_id=result.model_result.model_id if result.model_result else None,
            prompt_version=ASSISTANT_GENERATION_POLICY_VERSION,
            created_at=now,
        )
        session.add(turn)
        await session.flush()
        session.add(
            AssistantAuditEvent(
                user_id=user_id,
                conversation_id=conversation_id,
                turn_id=turn.id,
                event_type=result.answer.status.value,
                packet_id=result.packet_id,
                model_id=turn.model_id,
                prompt_version=turn.prompt_version,
                policy_version=result.answer.safety_policy_version,
                evidence_ids=list(result.used_evidence_ids),
                latency_ms=latency_ms,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                created_at=now,
            )
        )
        await session.flush()
        return AssistantHistoryTurn(turn.id, ordinal, normalized_question, result.answer, now)

    async def recent(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        conversation_id: UUID,
        limit: int = MAX_HISTORY_PAGE,
    ) -> tuple[AssistantHistoryTurn, ...]:
        _owner(user_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_HISTORY_PAGE:
            raise ValueError("History page limit is outside policy.")
        now = self._clock.now()
        rows = (await session.scalars(
            select(AssistantConversationTurn)
            .join(AssistantConversation, AssistantConversation.id == AssistantConversationTurn.conversation_id)
            .where(
                AssistantConversation.user_id == user_id,
                AssistantConversation.id == conversation_id,
                AssistantConversation.expires_at > now,
                AssistantConversationTurn.user_id == user_id,
            )
            .order_by(AssistantConversationTurn.ordinal.desc())
            .limit(limit)
        )).all()
        return tuple(
            AssistantHistoryTurn(
                row.id, row.ordinal,
                self._decrypt(row.question_ciphertext),
                _restore_answer(json.loads(self._decrypt(row.answer_ciphertext))),
                row.created_at,
            )
            for row in reversed(rows)
        )

    def _decrypt(self, token: str) -> str:
        try:
            return self._cipher.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise ValueError("Assistant history cannot be decrypted with configured keys.") from exc

    async def delete(self, session: AsyncSession, *, user_id: UUID, conversation_id: UUID) -> bool:
        """Erase conversation, turns, and audit records via database cascade."""

        _owner(user_id)
        result = await session.execute(
            delete(AssistantConversation).where(
                AssistantConversation.id == conversation_id,
                AssistantConversation.user_id == user_id,
            )
        )
        return bool(result.rowcount)

    async def erase_user(self, session: AsyncSession, *, user_id: UUID) -> int:
        _owner(user_id)
        result = await session.execute(
            delete(AssistantConversation).where(AssistantConversation.user_id == user_id)
        )
        return result.rowcount

    async def purge_expired(self, session: AsyncSession, *, limit: int = 100) -> int:
        """Explicit bounded retention job; Phase 13 schedules its execution."""

        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise ValueError("Retention batch limit is outside policy.")
        expired = select(AssistantConversation.id).where(
            AssistantConversation.expires_at <= self._clock.now()
        ).order_by(AssistantConversation.expires_at, AssistantConversation.id).limit(limit)
        result = await session.execute(delete(AssistantConversation).where(AssistantConversation.id.in_(expired)))
        return result.rowcount


def _owner(user_id: UUID) -> None:
    if not isinstance(user_id, UUID):
        raise PermissionError("Authenticated owner identity is required.")


def _answer_document(answer: AssistantAnswer) -> dict[str, object]:
    """Explicit public-field allowlist; no raw packet, model text, or secrets."""

    return {
        "intent": answer.intent.value,
        "status": answer.status.value,
        "answer": answer.answer,
        "evidence_summary": list(answer.evidence_summary),
        "citations": [
            {
                "source": item.source.value,
                "reference": item.reference,
                "label": item.label,
                "cutoff_at": item.cutoff_at.isoformat(),
                "policy_version": item.policy_version,
                "reliability": item.reliability.value,
            }
            for item in answer.citations
        ],
        "reliability": answer.reliability.value,
        "warnings": [item.value for item in answer.warnings],
        "suggested_questions": list(answer.suggested_questions),
        "refusal_reason": answer.refusal_reason.value if answer.refusal_reason else None,
        "contract_version": answer.contract_version,
        "safety_policy_version": answer.safety_policy_version,
    }


def _restore_answer(document: dict[str, object]) -> AssistantAnswer:
    return AssistantAnswer(
        intent=AssistantIntent(document["intent"]),
        status=AssistantAnswerStatus(document["status"]),
        answer=document["answer"],
        evidence_summary=tuple(document["evidence_summary"]),
        citations=tuple(
            AssistantCitation(
                source=AssistantEvidenceSource(item["source"]),
                reference=item["reference"],
                label=item["label"],
                cutoff_at=datetime.fromisoformat(item["cutoff_at"]),
                policy_version=item["policy_version"],
                reliability=AssistantReliability(item["reliability"]),
            )
            for item in document["citations"]
        ),
        reliability=AssistantReliability(document["reliability"]),
        warnings=tuple(AssistantWarning(item) for item in document["warnings"]),
        suggested_questions=tuple(document["suggested_questions"]),
        refusal_reason=AssistantRefusalReason(document["refusal_reason"]) if document["refusal_reason"] else None,
        contract_version=document["contract_version"],
        safety_policy_version=document["safety_policy_version"],
    )


__all__ = ["AssistantHistoryService", "AssistantHistoryTurn", "RETENTION_DAYS"]
