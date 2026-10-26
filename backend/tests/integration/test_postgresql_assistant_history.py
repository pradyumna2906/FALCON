"""PostgreSQL ownership, append-only records, retention, and erasure."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from falcon_api.assistant import (
    AssistantClaimKind,
    AssistantEvidenceRecord,
    AssistantEvidenceSource,
    AssistantGeneratedClaim,
    AssistantHistoryService,
    AssistantIntent,
    AssistantModelOutput,
    AssistantModelResult,
    AssistantModelUsage,
    AssistantReliability,
    GroundedAssistantGenerator,
    build_evidence_packet,
    hash_idempotency_key,
)
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.assistant import AssistantAuditEvent, AssistantConversation, AssistantConversationTurn
from falcon_api.models.enums import UserStatus
from falcon_api.models.user import User


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
IDEMPOTENCY_KEY = "postgres-message-key-0001"


class FixedClock:
    def __init__(self, instant=NOW):
        self.instant = instant

    def now(self):
        return self.instant


class FixedModel:
    async def generate(self, packet):
        return AssistantModelResult(
            output=AssistantModelOutput(claims=(AssistantGeneratedClaim(
                kind=AssistantClaimKind.FORECAST,
                text="Expected savings are ₹8,500.",
                evidence_ids=(packet.evidence[0].evidence_id,),
            ),)),
            usage=AssistantModelUsage(100, 20, 1),
            provider_id="fixture", model_id="fixture-v1",
        )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    command.upgrade(Config(str(ROOT / "backend" / "alembic.ini")), "head")
    yield


def test_owner_scope_append_only_erasure_and_retention():
    asyncio.run(_exercise_history())


async def _exercise_history():
    settings = Settings(
        _env_file=ROOT / ".env", env=AppEnvironment.TEST,
        debug=False, docs_enabled=False, cors_allowed_origins=(),
    )
    resources = create_database_resources(settings)
    owner, stranger = uuid4(), uuid4()
    key = Fernet.generate_key()
    service = AssistantHistoryService(encryption_keys=(key,), clock=FixedClock())
    try:
        async with transaction_scope(resources.session_factory) as session:
            for user_id in (owner, stranger):
                session.add(User(
                    id=user_id, email=f"assistant-{user_id.hex}@falcon.test",
                    status=UserStatus.ACTIVE, timezone="Asia/Kolkata",
                    default_currency="INR", created_at=NOW, updated_at=NOW,
                ))
        evidence = AssistantEvidenceRecord(
            source=AssistantEvidenceSource.FORECAST,
            reference="forecast-1", label="Savings forecast",
            cutoff_at=NOW, policy_version="2026.1",
            reliability=AssistantReliability.NORMAL,
            payload={"currency": "INR", "points": ({"expected_value": Decimal("8500")},)},
        )
        packet = build_evidence_packet(
            question="Explain savings", intent=AssistantIntent.EXPLAIN_FORECAST,
            user_id=owner, requested_sources=(AssistantEvidenceSource.FORECAST,),
            evidence=(evidence,), created_at=NOW,
        )
        verified = await GroundedAssistantGenerator(FixedModel()).generate(packet)
        async with transaction_scope(resources.session_factory) as session:
            conversation = await service.create(session, user_id=owner)
            conversation_id = conversation.id
            turn = await service.append(
                session, user_id=owner, conversation_id=conversation_id,
                question=packet.question, result=verified, latency_ms=100,
                idempotency_key=IDEMPOTENCY_KEY,
            )
            assert turn is not None

        async with transaction_scope(resources.session_factory) as session:
            assert await service.recent(session, user_id=stranger, conversation_id=conversation_id) == ()
            assert await service.append(
                session, user_id=stranger, conversation_id=conversation_id,
                question=packet.question, result=verified, latency_ms=100,
            ) is None
            assert not await service.delete(session, user_id=stranger, conversation_id=conversation_id)
            history = await service.recent(session, user_id=owner, conversation_id=conversation_id)
            assert len(history) == 1 and history[0].answer == verified.answer
            exists, replay = await service.lock_and_find(
                session,
                user_id=owner,
                conversation_id=conversation_id,
                idempotency_key=IDEMPOTENCY_KEY,
            )
            assert exists and replay == history[0]
            audit = await session.scalar(select(AssistantAuditEvent).where(AssistantAuditEvent.user_id == owner))
            assert audit is not None and audit.evidence_ids == [evidence.evidence_id]
            stored = await session.scalar(
                select(AssistantConversationTurn).where(
                    AssistantConversationTurn.user_id == owner
                )
            )
            assert stored is not None
            assert stored.idempotency_key_hash == hash_idempotency_key(
                IDEMPOTENCY_KEY
            )

        with pytest.raises(DBAPIError):
            async with transaction_scope(resources.session_factory) as session:
                await session.execute(update(AssistantConversationTurn).where(
                    AssistantConversationTurn.user_id == owner
                ).values(question_ciphertext="changed"))
        with pytest.raises(IntegrityError):
            async with transaction_scope(resources.session_factory) as session:
                session.add(AssistantConversationTurn(
                    user_id=stranger, conversation_id=conversation_id,
                    ordinal=2, question_ciphertext="encrypted", answer_ciphertext="encrypted",
                    prompt_version="2026.1", created_at=NOW,
                ))
                await session.flush()

        async with transaction_scope(resources.session_factory) as session:
            old = await AssistantHistoryService(encryption_keys=(key,), clock=FixedClock(NOW - timedelta(days=91))).create(session, user_id=owner)
            old_id = old.id
        async with transaction_scope(resources.session_factory) as session:
            assert await service.purge_expired(session) >= 1
            assert await session.scalar(select(AssistantConversation.id).where(AssistantConversation.id == old_id)) is None
            assert await service.delete(session, user_id=owner, conversation_id=conversation_id)
        async with transaction_scope(resources.session_factory) as session:
            assert await session.scalar(select(func.count()).select_from(AssistantConversationTurn).where(AssistantConversationTurn.user_id == owner)) == 0
            assert await session.scalar(select(func.count()).select_from(AssistantAuditEvent).where(AssistantAuditEvent.user_id == owner)) == 0
            await session.execute(delete(User).where(User.id.in_((owner, stranger))))
    finally:
        await resources.engine.dispose()
