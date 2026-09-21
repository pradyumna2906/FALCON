"""Repository-level Phase 12 Batch 1 boundary tests."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[3]


def test_phase_12_implementation_record_freezes_batch_1_and_deferrals() -> None:
    document = (_ROOT / "docs/assistant/PHASE_12_IMPLEMENTATION.md").read_text(
        encoding="utf-8"
    )

    for heading in (
        "Checkpoint 12.0 — readiness and architecture",
        "Checkpoint 12.1 — intents and response contract",
        "Checkpoint 12.2 — privacy, authorization, and threats",
        "Batch 1 security invariants",
        "Deferred checkpoints",
    ):
        assert heading in document
    for boundary in (
        "It cannot edit a profile, account, transaction, budget, goal, contribution",
        "Raw financial data is not embedded or semantically indexed.",
        "Generated answers require evidence summaries and citations.",
        "Batch 1 deliberately adds no conversation table",
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
