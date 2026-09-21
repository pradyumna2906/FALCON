"""Repository-level Phase 12 retrieval-boundary tests."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]


def test_phase_12_implementation_record_freezes_batches_1_and_2() -> None:
    document = (_ROOT / "docs/assistant/PHASE_12_IMPLEMENTATION.md").read_text(
        encoding="utf-8"
    )

    for heading in (
        "Checkpoint 12.0 — readiness and architecture",
        "Checkpoint 12.1 — intents and response contract",
        "Checkpoint 12.2 — privacy, authorization, and threats",
        "Batch 1 security invariants",
        "Checkpoint 12.3 — owner-scoped structured evidence registry",
        "Checkpoint 12.4 — curated knowledge ingestion and persistence",
        "Checkpoint 12.5 — bounded retrieval and deterministic reranking",
        "Batch 2 security and integrity invariants",
        "Deferred checkpoints",
    ):
        assert heading in document
    for boundary in (
        "It cannot edit a profile, account, transaction, budget, goal, contribution",
        "Raw financial data is not embedded or semantically indexed.",
        "Generated answers require evidence summaries and citations.",
        "Batches 1–2 deliberately add no conversation table",
        "Raw financial evidence is never inserted into a full-text or embedding index.",
    ):
        assert boundary in document


def test_assistant_adr_selects_postgresql_and_provider_neutral_boundary() -> None:
    document = (
        _ROOT / "docs/adr/0004-grounded-assistant-and-rag-architecture.md"
    ).read_text(encoding="utf-8")
    dependencies = (_ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")

    assert "Status: Accepted" in document
    assert "structured, owner-scoped PostgreSQL" in document
    assert "provider-neutral" in document.casefold()
    assert "Raw accounts, statements, transactions" in document
    assert "no financial write tools" in document
    for premature_dependency in ("langchain", "pgvector", "openai==", "anthropic=="):
        assert premature_dependency not in dependencies.casefold()


def test_project_status_marks_phase_11_merged_and_phase_12_active() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Phases 0–11 are merged" in readme
    assert "Phase 12 grounded assistant and RAG" in readme
