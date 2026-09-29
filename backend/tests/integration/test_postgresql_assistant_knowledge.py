"""Real PostgreSQL curated-knowledge retrieval and immutability tests."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from falcon_api.assistant import (
    AssistantKnowledgeService,
    AssistantKnowledgeTopic,
    KnowledgeDocumentInput,
)
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.models.assistant import AssistantKnowledgeChunk


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


def integration_settings() -> Settings:
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def test_curated_knowledge_is_searchable_versioned_retirable_and_immutable() -> None:
    asyncio.run(_exercise_curated_knowledge())


async def _exercise_curated_knowledge() -> None:
    resources = create_database_resources(integration_settings())
    service = AssistantKnowledgeService(clock=FixedClock())
    slug = f"emergency-fund-{uuid4().hex}"
    chunk_id = None
    try:
        async with transaction_scope(resources.session_factory) as session:
            document = await service.ingest(
                session,
                source=KnowledgeDocumentInput(
                    slug=slug,
                    version="2026.1",
                    title="Emergency Fund Guidance",
                    source_uri="https://example.org/financial-literacy/emergency-fund",
                    topics=(AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
                    published_at=datetime(2026, 9, 1, tzinfo=UTC),
                    content=(
                        "# Emergency reserve\n\n"
                        "An emergency fund protects essential expenses during "
                        "an unexpected income disruption."
                    ),
                ),
            )
            chunk_id = document.chunks[0].id

        async with transaction_scope(resources.session_factory) as session:
            retrieval = await service.retrieve(
                session,
                query_text="emergency fund income disruption",
                topics=(AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
                limit=3,
            )
            assert retrieval.hits
            assert retrieval.hits[0].candidate.slug == slug
            assert len(retrieval.retrieval_id) == 64

        with pytest.raises(DBAPIError):
            async with transaction_scope(resources.session_factory) as session:
                await session.execute(
                    update(AssistantKnowledgeChunk)
                    .where(AssistantKnowledgeChunk.id == chunk_id)
                    .values(content="mutated")
                )

        async with transaction_scope(resources.session_factory) as session:
            retired = await service.retire(
                session,
                slug=slug,
                version="2026.1",
            )
            assert retired.retired_at == _NOW

        async with transaction_scope(resources.session_factory) as session:
            retrieval = await service.retrieve(
                session,
                query_text="emergency fund income disruption",
                topics=(AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
                limit=3,
            )
            assert all(item.candidate.slug != slug for item in retrieval.hits)
    finally:
        await resources.engine.dispose()
