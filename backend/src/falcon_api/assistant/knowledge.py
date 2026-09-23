"""Curated knowledge ingestion, PostgreSQL retrieval, and deterministic reranking."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from falcon_api.assistant.evidence import (
    AssistantEvidenceAdapter,
    AssistantEvidenceQuery,
    AssistantEvidenceRecord,
)
from falcon_api.assistant.semantics import (
    ASSISTANT_KNOWLEDGE_POLICY_VERSION,
    ASSISTANT_RETRIEVAL_POLICY_VERSION,
    MAX_KNOWLEDGE_CHUNK_CHARACTERS,
    MAX_KNOWLEDGE_CHUNKS_PER_DOCUMENT,
    MAX_KNOWLEDGE_DOCUMENT_CHARACTERS,
    MAX_KNOWLEDGE_HEADING_CHARACTERS,
    MAX_KNOWLEDGE_QUERY_CHARACTERS,
    MAX_KNOWLEDGE_RESULTS,
    MAX_KNOWLEDGE_SLUG_CHARACTERS,
    MAX_KNOWLEDGE_SOURCE_URI_CHARACTERS,
    MAX_KNOWLEDGE_TITLE_CHARACTERS,
    MAX_KNOWLEDGE_VERSION_CHARACTERS,
    MIN_KNOWLEDGE_CHUNK_CHARACTERS,
    MAX_CITATION_LABEL_CHARACTERS,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantKnowledgeTopic,
    AssistantReliability,
    AssistantRetrievalReason,
)
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.models.assistant import (
    AssistantKnowledgeChunk,
    AssistantKnowledgeDocument,
)


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SCORE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentInput:
    """Reviewed public source supplied by an offline curator."""

    slug: str
    version: str
    title: str
    source_uri: str
    topics: tuple[AssistantKnowledgeTopic, ...]
    published_at: datetime
    content: str


@dataclass(frozen=True, slots=True)
class KnowledgeChunkDraft:
    """Deterministic chunk produced before persistence."""

    ordinal: int
    heading: str
    content: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class KnowledgeSearchCandidate:
    """One PostgreSQL full-text candidate before deterministic reranking."""

    document_id: UUID
    chunk_id: UUID
    slug: str
    version: str
    title: str
    source_uri: str
    topics: tuple[AssistantKnowledgeTopic, ...]
    published_at: datetime
    retired_at: datetime | None
    ordinal: int
    heading: str
    content: str
    text_rank: Decimal


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    """One bounded public excerpt with transparent lexical ranking evidence."""

    candidate: KnowledgeSearchCandidate
    score: Decimal
    reasons: tuple[AssistantRetrievalReason, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeRetrieval:
    """Stable result identity and ordered curated knowledge hits."""

    retrieval_id: str
    query_digest: str
    retrieved_at: datetime
    policy_version: str
    hits: tuple[KnowledgeHit, ...]


class AssistantKnowledgeRepository:
    """Persist and search only curated public assistant knowledge."""

    async def get_version(
        self,
        session: AsyncSession,
        *,
        slug: str,
        version: str,
    ) -> AssistantKnowledgeDocument | None:
        return await session.scalar(
            select(AssistantKnowledgeDocument)
            .options(selectinload(AssistantKnowledgeDocument.chunks))
            .where(
                AssistantKnowledgeDocument.slug == slug,
                AssistantKnowledgeDocument.version == version,
            )
        )

    async def create(
        self,
        session: AsyncSession,
        *,
        document: AssistantKnowledgeDocument,
    ) -> AssistantKnowledgeDocument:
        session.add(document)
        await session.flush()
        return document

    async def retire(
        self,
        session: AsyncSession,
        *,
        document: AssistantKnowledgeDocument,
        retired_at: datetime,
    ) -> AssistantKnowledgeDocument:
        if document.retired_at is not None:
            raise ValueError("Knowledge document version is already retired.")
        if retired_at < document.published_at:
            raise ValueError("Knowledge retirement cannot precede publication.")
        result = await session.execute(
            update(AssistantKnowledgeDocument)
            .where(
                AssistantKnowledgeDocument.id == document.id,
                AssistantKnowledgeDocument.retired_at.is_(None),
            )
            .values(
                retired_at=retired_at,
                updated_at=retired_at,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ValueError("Knowledge document version is already retired.")
        await session.refresh(document)
        return document

    async def search(
        self,
        session: AsyncSession,
        *,
        query_text: str,
        topics: tuple[AssistantKnowledgeTopic, ...],
        cutoff_at: datetime,
        limit: int,
    ) -> tuple[KnowledgeSearchCandidate, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("Knowledge candidate limit must be between 1 and 50.")
        query = func.websearch_to_tsquery("english", query_text)
        rank = func.ts_rank_cd(AssistantKnowledgeChunk.search_vector, query)
        statement = (
            select(AssistantKnowledgeChunk, AssistantKnowledgeDocument, rank.label("text_rank"))
            .join(
                AssistantKnowledgeDocument,
                AssistantKnowledgeDocument.id == AssistantKnowledgeChunk.document_id,
            )
            .where(
                AssistantKnowledgeDocument.retired_at.is_(None),
                AssistantKnowledgeDocument.published_at <= cutoff_at,
                AssistantKnowledgeChunk.search_vector.op("@@")(query),
            )
        )
        if topics:
            statement = statement.where(
                or_(
                    *(
                        AssistantKnowledgeDocument.topics.contains([topic.value])
                        for topic in topics
                    )
                )
            )
        statement = statement.order_by(
            desc(rank),
            AssistantKnowledgeDocument.published_at.desc(),
            AssistantKnowledgeDocument.slug.asc(),
            AssistantKnowledgeDocument.version.desc(),
            AssistantKnowledgeChunk.ordinal.asc(),
        ).limit(limit)
        rows = (await session.execute(statement)).all()
        return tuple(
            KnowledgeSearchCandidate(
                document_id=document.id,
                chunk_id=chunk.id,
                slug=document.slug,
                version=document.version,
                title=document.title,
                source_uri=document.source_uri,
                topics=tuple(AssistantKnowledgeTopic(item) for item in document.topics),
                published_at=document.published_at,
                retired_at=document.retired_at,
                ordinal=chunk.ordinal,
                heading=chunk.heading,
                content=chunk.content,
                text_rank=Decimal(str(text_rank)),
            )
            for chunk, document, text_rank in rows
        )


class AssistantKnowledgeService:
    """Validate offline curation and provide bounded lexical RAG retrieval."""

    def __init__(
        self,
        *,
        repository: AssistantKnowledgeRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or AssistantKnowledgeRepository()
        self._clock = clock or SystemClock()

    async def ingest(
        self,
        session: AsyncSession,
        *,
        source: KnowledgeDocumentInput,
    ) -> AssistantKnowledgeDocument:
        normalized = validate_knowledge_document(source, now=self._clock.now())
        if await self._repository.get_version(
            session,
            slug=normalized.slug,
            version=normalized.version,
        ) is not None:
            raise ValueError("Knowledge document slug and version already exist.")
        drafts = chunk_knowledge_document(normalized.content, title=normalized.title)
        now = self._clock.now()
        document_id = uuid4()
        document = AssistantKnowledgeDocument(
            id=document_id,
            slug=normalized.slug,
            version=normalized.version,
            title=normalized.title,
            source_uri=normalized.source_uri,
            topics=[item.value for item in normalized.topics],
            content_sha256=_digest(normalized.content),
            policy_version=ASSISTANT_KNOWLEDGE_POLICY_VERSION,
            published_at=normalized.published_at,
            retired_at=None,
            created_at=now,
            updated_at=now,
            chunks=[
                AssistantKnowledgeChunk(
                    id=uuid4(),
                    document_id=document_id,
                    ordinal=item.ordinal,
                    heading=item.heading,
                    content=item.content,
                    character_count=len(item.content),
                    content_sha256=item.content_sha256,
                    created_at=now,
                    updated_at=now,
                )
                for item in drafts
            ],
        )
        return await self._repository.create(session, document=document)

    async def retire(
        self,
        session: AsyncSession,
        *,
        slug: str,
        version: str,
    ) -> AssistantKnowledgeDocument:
        document = await self._repository.get_version(
            session,
            slug=slug,
            version=version,
        )
        if document is None:
            raise ValueError("Knowledge document version was not found.")
        return await self._repository.retire(
            session,
            document=document,
            retired_at=self._clock.now(),
        )

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        query_text: str,
        topics: tuple[AssistantKnowledgeTopic, ...] = (),
        limit: int = 5,
    ) -> KnowledgeRetrieval:
        query = normalize_knowledge_query(query_text)
        resolved_topics = tuple(AssistantKnowledgeTopic(item) for item in topics)
        if len(set(resolved_topics)) != len(resolved_topics):
            raise ValueError("Knowledge topics must be unique.")
        if isinstance(limit, bool) or not 1 <= limit <= MAX_KNOWLEDGE_RESULTS:
            raise ValueError("Knowledge result limit must be between 1 and 10.")
        retrieved_at = self._clock.now()
        candidates = await self._repository.search(
            session,
            query_text=query,
            topics=resolved_topics,
            cutoff_at=retrieved_at,
            limit=min(50, limit * 5),
        )
        hits = rerank_knowledge_candidates(
            query_text=query,
            topics=resolved_topics,
            candidates=candidates,
            limit=limit,
        )
        query_digest = _digest(
            json.dumps(
                {"query": query.casefold(), "topics": [item.value for item in resolved_topics]},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        retrieval_id = _digest(
            json.dumps(
                {
                    "query_digest": query_digest,
                    "retrieved_at": retrieved_at.isoformat(),
                    "policy_version": ASSISTANT_RETRIEVAL_POLICY_VERSION,
                    "hits": [
                        {
                            "document_id": str(item.candidate.document_id),
                            "chunk_id": str(item.candidate.chunk_id),
                            "score": str(item.score),
                        }
                        for item in hits
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return KnowledgeRetrieval(
            retrieval_id=retrieval_id,
            query_digest=query_digest,
            retrieved_at=retrieved_at,
            policy_version=ASSISTANT_RETRIEVAL_POLICY_VERSION,
            hits=hits,
        )


class KnowledgeEvidenceAdapter(AssistantEvidenceAdapter):
    """Expose curated public retrieval through the closed evidence registry."""

    source = AssistantEvidenceSource.KNOWLEDGE

    def __init__(self, service: AssistantKnowledgeService | None = None) -> None:
        self._service = service or AssistantKnowledgeService()

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        user_id: UUID | None,
        intent: AssistantIntent,
        query: AssistantEvidenceQuery,
    ) -> tuple[AssistantEvidenceRecord, ...]:
        del user_id, intent
        retrieval = await self._service.retrieve(
            session,
            query_text=query.text or "",
            topics=query.topics,
            limit=min(query.limit, MAX_KNOWLEDGE_RESULTS),
        )
        records = []
        for hit in retrieval.hits:
            label = f"{hit.candidate.title} — {hit.candidate.heading}"
            records.append(
                AssistantEvidenceRecord(
                    source=self.source,
                    reference=(
                        f"{hit.candidate.document_id}:{hit.candidate.chunk_id}"
                    ),
                    label=label[:MAX_CITATION_LABEL_CHARACTERS].rstrip(),
                    cutoff_at=retrieval.retrieved_at,
                    policy_version=retrieval.policy_version,
                    reliability=AssistantReliability.NORMAL,
                    payload={
                        "document_id": hit.candidate.document_id,
                        "chunk_id": hit.candidate.chunk_id,
                        "title": hit.candidate.title,
                        "heading": hit.candidate.heading,
                        "content": hit.candidate.content,
                        "version": hit.candidate.version,
                        "source_uri": hit.candidate.source_uri,
                        "topics": tuple(
                            item.value for item in hit.candidate.topics
                        ),
                        "published_at": hit.candidate.published_at,
                        "retired_at": hit.candidate.retired_at,
                        "retrieval_score": hit.score,
                        "retrieval_reasons": tuple(
                            item.value for item in hit.reasons
                        ),
                    },
                )
            )
        return tuple(records)


def validate_knowledge_document(
    source: KnowledgeDocumentInput,
    *,
    now: datetime,
) -> KnowledgeDocumentInput:
    """Normalize and reject non-public, unbounded, or ambiguous curation input."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Knowledge validation time must be timezone-aware.")
    slug = source.slug.strip().casefold()
    version = source.version.strip()
    title = _single_line(source.title, "title", MAX_KNOWLEDGE_TITLE_CHARACTERS)
    uri = source.source_uri.strip()
    content = _normalize_content(source.content)
    topics = tuple(AssistantKnowledgeTopic(item) for item in source.topics)
    if not slug or len(slug) > MAX_KNOWLEDGE_SLUG_CHARACTERS or _SLUG_RE.fullmatch(slug) is None:
        raise ValueError("Knowledge slug must use bounded lowercase kebab-case.")
    if not version or len(version) > MAX_KNOWLEDGE_VERSION_CHARACTERS:
        raise ValueError("Knowledge version must be bounded and non-empty.")
    parsed = urlsplit(uri)
    if len(uri) > MAX_KNOWLEDGE_SOURCE_URI_CHARACTERS or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Knowledge source URI must be a bounded public HTTPS URL.")
    if not topics or len(set(topics)) != len(topics):
        raise ValueError("Knowledge topics must be non-empty and unique.")
    if source.published_at.tzinfo is None or source.published_at.utcoffset() is None:
        raise ValueError("Knowledge publication time must be timezone-aware.")
    if source.published_at > now:
        raise ValueError("Knowledge cannot be published in the future.")
    if not content or len(content) > MAX_KNOWLEDGE_DOCUMENT_CHARACTERS:
        raise ValueError("Knowledge content must be non-empty and bounded.")
    return KnowledgeDocumentInput(
        slug=slug,
        version=version,
        title=title,
        source_uri=uri,
        topics=topics,
        published_at=source.published_at,
        content=content,
    )


def chunk_knowledge_document(content: str, *, title: str) -> tuple[KnowledgeChunkDraft, ...]:
    """Split normalized Markdown by headings and bounded paragraph groups."""

    normalized = _normalize_content(content)
    default_heading = _single_line(title, "title", MAX_KNOWLEDGE_HEADING_CHARACTERS)
    sections: list[tuple[str, list[str]]] = []
    heading = default_heading
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", normalized):
        item = block.strip()
        if not item:
            continue
        lines = item.splitlines()
        if lines[0].lstrip().startswith("#"):
            if paragraphs:
                sections.append((heading, paragraphs))
                paragraphs = []
            heading = _single_line(
                lines[0].lstrip("# "),
                "heading",
                MAX_KNOWLEDGE_HEADING_CHARACTERS,
            )
            remainder = "\n".join(lines[1:]).strip()
            if remainder:
                paragraphs.append(remainder)
        else:
            paragraphs.append(item)
    if paragraphs:
        sections.append((heading, paragraphs))
    drafts: list[KnowledgeChunkDraft] = []
    for section_heading, items in sections:
        buffer = ""
        for paragraph in items:
            if len(paragraph) > MAX_KNOWLEDGE_CHUNK_CHARACTERS:
                raise ValueError("A knowledge paragraph exceeds the chunk limit.")
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= MAX_KNOWLEDGE_CHUNK_CHARACTERS:
                buffer = candidate
                continue
            drafts.append(_chunk_draft(len(drafts) + 1, section_heading, buffer))
            buffer = paragraph
        if buffer:
            drafts.append(_chunk_draft(len(drafts) + 1, section_heading, buffer))
    if not drafts or len(drafts) > MAX_KNOWLEDGE_CHUNKS_PER_DOCUMENT:
        raise ValueError("Knowledge document must produce a bounded chunk set.")
    if len(drafts) > 1 and len(drafts[-1].content) < MIN_KNOWLEDGE_CHUNK_CHARACTERS:
        previous = drafts[-2]
        combined = f"{previous.content}\n\n{drafts[-1].content}"
        if len(combined) <= MAX_KNOWLEDGE_CHUNK_CHARACTERS:
            drafts[-2:] = [_chunk_draft(previous.ordinal, previous.heading, combined)]
    if any(len(item.content) < MIN_KNOWLEDGE_CHUNK_CHARACTERS for item in drafts):
        raise ValueError("Knowledge chunks must contain enough explanatory text.")
    hashes = tuple(item.content_sha256 for item in drafts)
    if len(set(hashes)) != len(hashes):
        raise ValueError("Knowledge chunks must be unique within a document.")
    return tuple(
        KnowledgeChunkDraft(
            ordinal=index,
            heading=item.heading,
            content=item.content,
            content_sha256=item.content_sha256,
        )
        for index, item in enumerate(drafts, start=1)
    )


def normalize_knowledge_query(value: str) -> str:
    """Normalize one user-derived lexical query without interpreting commands."""

    query = " ".join(value.split())
    if not query or len(query) > MAX_KNOWLEDGE_QUERY_CHARACTERS:
        raise ValueError("Knowledge query must be non-empty and bounded.")
    if not _TOKEN_RE.search(query.casefold()):
        raise ValueError("Knowledge query must contain searchable text.")
    return query


def rerank_knowledge_candidates(
    *,
    query_text: str,
    topics: tuple[AssistantKnowledgeTopic, ...],
    candidates: tuple[KnowledgeSearchCandidate, ...],
    limit: int,
) -> tuple[KnowledgeHit, ...]:
    """Rerank PostgreSQL candidates with transparent deterministic lexical signals."""

    query = normalize_knowledge_query(query_text)
    if isinstance(limit, bool) or not 1 <= limit <= MAX_KNOWLEDGE_RESULTS:
        raise ValueError("Knowledge result limit must be between 1 and 10.")
    query_folded = query.casefold()
    query_tokens = frozenset(_TOKEN_RE.findall(query_folded))
    requested_topics = frozenset(topics)
    hits: list[KnowledgeHit] = []
    seen: set[tuple[UUID, UUID]] = set()
    for candidate in candidates:
        key = (candidate.document_id, candidate.chunk_id)
        if key in seen:
            raise ValueError("Knowledge candidates must be unique.")
        seen.add(key)
        title = candidate.title.casefold()
        heading = candidate.heading.casefold()
        content = candidate.content.casefold()
        candidate_tokens = frozenset(_TOKEN_RE.findall(f"{title} {heading} {content}"))
        overlap = Decimal(len(query_tokens & candidate_tokens)) / Decimal(len(query_tokens))
        text_score = min(Decimal("1"), max(Decimal("0"), candidate.text_rank))
        title_match = bool(query_tokens & frozenset(_TOKEN_RE.findall(title)))
        heading_match = bool(query_tokens & frozenset(_TOKEN_RE.findall(heading)))
        phrase_match = query_folded in f"{title} {heading} {content}"
        topic_match = bool(requested_topics & frozenset(candidate.topics))
        score = (
            text_score * Decimal("0.55")
            + overlap * Decimal("0.25")
            + Decimal("0.08") * int(title_match)
            + Decimal("0.05") * int(heading_match)
            + Decimal("0.05") * int(phrase_match)
            + Decimal("0.02") * int(topic_match)
        ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)
        reasons = [AssistantRetrievalReason.FULL_TEXT_MATCH]
        if title_match:
            reasons.append(AssistantRetrievalReason.TITLE_MATCH)
        if heading_match:
            reasons.append(AssistantRetrievalReason.HEADING_MATCH)
        if topic_match:
            reasons.append(AssistantRetrievalReason.TOPIC_MATCH)
        if phrase_match:
            reasons.append(AssistantRetrievalReason.PHRASE_MATCH)
        hits.append(KnowledgeHit(candidate=candidate, score=score, reasons=tuple(reasons)))
    hits.sort(
        key=lambda item: (
            -item.score,
            -item.candidate.published_at.timestamp(),
            item.candidate.slug,
            item.candidate.version,
            item.candidate.ordinal,
            str(item.candidate.chunk_id),
        )
    )
    return tuple(hits[:limit])


def _chunk_draft(ordinal: int, heading: str, content: str) -> KnowledgeChunkDraft:
    value = content.strip()
    if not value or len(value) > MAX_KNOWLEDGE_CHUNK_CHARACTERS:
        raise ValueError("Knowledge chunk must be non-empty and bounded.")
    return KnowledgeChunkDraft(
        ordinal=ordinal,
        heading=heading,
        content=value,
        content_sha256=_digest(value),
    )


def _single_line(value: str, label: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"Knowledge {label} must be bounded and non-empty.")
    return normalized


def _normalize_content(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "AssistantKnowledgeRepository",
    "AssistantKnowledgeService",
    "KnowledgeDocumentInput",
    "KnowledgeEvidenceAdapter",
    "KnowledgeHit",
    "KnowledgeRetrieval",
    "KnowledgeSearchCandidate",
    "chunk_knowledge_document",
    "normalize_knowledge_query",
    "rerank_knowledge_candidates",
    "validate_knowledge_document",
]
