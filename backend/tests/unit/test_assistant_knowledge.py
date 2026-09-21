"""Curated knowledge ingestion and deterministic retrieval tests."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.assistant import (
    ASSISTANT_KNOWLEDGE_POLICY_VERSION,
    AssistantEvidenceQuery,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantKnowledgeRepository,
    AssistantKnowledgeService,
    AssistantKnowledgeTopic,
    KnowledgeDocumentInput,
    KnowledgeEvidenceAdapter,
    KnowledgeSearchCandidate,
    chunk_knowledge_document,
    normalize_knowledge_query,
    rerank_knowledge_candidates,
    validate_knowledge_document,
)
from falcon_api.models.assistant import AssistantKnowledgeChunk


NOW = datetime(2026, 9, 22, 10, tzinfo=UTC)


class FixedClock:
    def now(self):
        return NOW


def _source(**changes) -> KnowledgeDocumentInput:
    values = {
        "slug": "emergency-fund-basics",
        "version": "2026.1",
        "title": "Emergency Fund Basics",
        "source_uri": "https://example.org/guides/emergency-fund",
        "topics": (
            AssistantKnowledgeTopic.EMERGENCY_FUNDS,
            AssistantKnowledgeTopic.SAVINGS,
        ),
        "published_at": datetime(2026, 9, 1, tzinfo=UTC),
        "content": (
            "# Why emergency funds matter\n\n"
            "An emergency fund protects essential expenses when income is disrupted.\n\n"
            "# Building the reserve\n\n"
            "Start with a bounded target and increase it as circumstances change."
        ),
    }
    values.update(changes)
    return KnowledgeDocumentInput(**values)


def _candidate(**changes) -> KnowledgeSearchCandidate:
    values = {
        "document_id": uuid4(),
        "chunk_id": uuid4(),
        "slug": "emergency-fund-basics",
        "version": "2026.1",
        "title": "Emergency Fund Basics",
        "source_uri": "https://example.org/guides/emergency-fund",
        "topics": (AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
        "published_at": datetime(2026, 9, 1, tzinfo=UTC),
        "retired_at": None,
        "ordinal": 1,
        "heading": "Building the reserve",
        "content": "Build an emergency fund for essential expenses and income disruption.",
        "text_rank": Decimal("0.8"),
    }
    values.update(changes)
    return KnowledgeSearchCandidate(**values)


def test_curated_document_validation_normalizes_public_metadata() -> None:
    result = validate_knowledge_document(
        _source(slug=" Emergency-Fund-Basics "),
        now=NOW,
    )

    assert result.slug == "emergency-fund-basics"
    assert result.title == "Emergency Fund Basics"
    assert result.content.count("\r") == 0
    assert result.topics[0] is AssistantKnowledgeTopic.EMERGENCY_FUNDS


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"slug": "not valid"}, "kebab-case"),
        ({"version": " "}, "version"),
        ({"title": " "}, "title"),
        ({"source_uri": "http://example.org/doc"}, "public HTTPS"),
        ({"source_uri": "https://user:pass@example.org/doc"}, "public HTTPS"),
        ({"source_uri": "https://example.org/doc#secret"}, "public HTTPS"),
        ({"topics": ()}, "non-empty and unique"),
        (
            {"topics": (AssistantKnowledgeTopic.SAVINGS,) * 2},
            "non-empty and unique",
        ),
        ({"published_at": datetime(2027, 1, 1, tzinfo=UTC)}, "future"),
        ({"published_at": datetime(2026, 1, 1)}, "timezone-aware"),
        ({"content": " "}, "content"),
    ],
)
def test_curated_document_validation_rejects_unsafe_input(changes, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_knowledge_document(_source(**changes), now=NOW)


def test_chunking_is_deterministic_heading_aware_and_bounded() -> None:
    chunks = chunk_knowledge_document(_source().content, title=_source().title)

    assert tuple(item.ordinal for item in chunks) == (1, 2)
    assert chunks[0].heading == "Why emergency funds matter"
    assert chunks[1].heading == "Building the reserve"
    assert all(len(item.content_sha256) == 64 for item in chunks)
    assert chunks == chunk_knowledge_document(_source().content, title=_source().title)

    with pytest.raises(ValueError, match="paragraph exceeds"):
        chunk_knowledge_document("x" * 4_001, title="Oversized")


def test_query_normalization_and_reranking_are_deterministic() -> None:
    exact = _candidate()
    weaker = _candidate(
        document_id=uuid4(),
        chunk_id=uuid4(),
        slug="general-savings",
        title="Savings",
        heading="Monthly habits",
        content="Save a regular amount each month.",
        text_rank=Decimal("0.7"),
    )

    hits = rerank_knowledge_candidates(
        query_text="  emergency   fund  ",
        topics=(AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
        candidates=(weaker, exact),
        limit=2,
    )

    assert normalize_knowledge_query("  emergency   fund  ") == "emergency fund"
    assert hits[0].candidate is exact
    assert hits[0].score > hits[1].score
    assert "topic_match" in {item.value for item in hits[0].reasons}

    with pytest.raises(ValueError, match="unique"):
        rerank_knowledge_candidates(
            query_text="emergency fund",
            topics=(),
            candidates=(exact, exact),
            limit=2,
        )
    with pytest.raises(ValueError, match="searchable"):
        normalize_knowledge_query("---")


def test_repository_search_uses_postgresql_full_text_and_active_cutoff() -> None:
    repository = AssistantKnowledgeRepository()
    session = AsyncMock(spec=AsyncSession)
    result = SimpleNamespace(all=lambda: [])
    session.execute.return_value = result

    rows = asyncio.run(
        repository.search(
            session,
            query_text="emergency fund",
            topics=(AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
            cutoff_at=NOW,
            limit=10,
        )
    )

    assert rows == ()
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "websearch_to_tsquery" in sql
    assert "@@" in sql
    assert "assistant_knowledge_documents.retired_at IS NULL" in sql
    assert "assistant_knowledge_documents.published_at <=" in sql
    assert "assistant_knowledge_documents.topics @>" in sql


def test_ingestion_persists_versioned_document_and_chunks_once() -> None:
    repository = AsyncMock(spec=AssistantKnowledgeRepository)
    repository.get_version.return_value = None
    repository.create.side_effect = lambda session, *, document: document
    service = AssistantKnowledgeService(repository=repository, clock=FixedClock())
    session = AsyncMock(spec=AsyncSession)

    document = asyncio.run(service.ingest(session, source=_source()))

    assert document.policy_version == ASSISTANT_KNOWLEDGE_POLICY_VERSION
    assert document.topics == ["emergency_funds", "savings"]
    assert len(document.chunks) == 2
    assert document.chunks[0].document_id == document.id
    repository.get_version.assert_awaited_once_with(
        session,
        slug="emergency-fund-basics",
        version="2026.1",
    )
    repository.create.assert_awaited_once()

    repository.get_version.return_value = document
    with pytest.raises(ValueError, match="already exist"):
        asyncio.run(service.ingest(session, source=_source()))


def test_retrieval_records_only_query_digest_and_public_provenance() -> None:
    repository = AsyncMock(spec=AssistantKnowledgeRepository)
    repository.search.return_value = (_candidate(),)
    service = AssistantKnowledgeService(repository=repository, clock=FixedClock())
    adapter = KnowledgeEvidenceAdapter(service)
    query = AssistantEvidenceQuery(
        source=AssistantEvidenceSource.KNOWLEDGE,
        text="How should I build an emergency fund?",
        topics=(AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
        limit=3,
    )

    records = asyncio.run(
        adapter.retrieve(
            AsyncMock(spec=AsyncSession),
            user_id=None,
            intent=AssistantIntent.FINANCIAL_EDUCATION,
            query=query,
        )
    )

    assert len(records) == 1
    assert records[0].source is AssistantEvidenceSource.KNOWLEDGE
    assert records[0].payload["title"] == "Emergency Fund Basics"
    assert "query" not in records[0].payload
    assert "emergency fund" not in records[0].evidence_id
    assert len(records[0].evidence_id) == 64


def test_knowledge_chunk_uses_generated_search_vector_and_gin_index() -> None:
    column = AssistantKnowledgeChunk.__table__.c.search_vector
    assert column.computed is not None
    assert "to_tsvector('english'" in str(column.computed.sqltext)
    assert {
        index.name for index in AssistantKnowledgeChunk.__table__.indexes
    } >= {"ix_assistant_knowledge_chunks_search_vector"}
