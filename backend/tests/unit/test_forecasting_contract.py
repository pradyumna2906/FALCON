"""Documentation contract checks for Phase 9 Batch 1."""

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_IMPLEMENTATION_DOCUMENT = (
    _REPOSITORY_ROOT / "docs" / "forecasting" / "PHASE_9_IMPLEMENTATION.md"
)


def test_phase_document_freezes_batch_one_boundaries() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    for statement in (
        "forecasting contract version: `2026.1`",
        "checkpoint 9.0",
        "checkpoint 9.1",
        "checkpoint 9.2",
        "authenticated principal",
        "gross income",
        "total expense",
        "net cash flow",
        "savings amount",
        "posted",
        "pending",
        "internal transfers",
        "adjustments",
        "currency conversion",
        "data cutoff",
        "created_at",
        "updated_at",
        "zero-filled",
        "daily",
        "monthly",
        "three complete calendar months",
        "chronological",
        "no model is trained",
        "phase 10",
    ):
        assert statement in content


def test_phase_document_freezes_quality_evaluation_and_baselines() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    for statement in (
        "checkpoint 9.3",
        "checkpoint 9.4",
        "checkpoint 9.5",
        "quality policy version `2026.1`",
        "unavailable",
        "provisional",
        "normal",
        "90 calendar periods",
        "median absolute deviation",
        "irregular_activity",
        "not a probability",
        "expanding-window rolling-origin",
        "final chronological test window",
        "random shuffle",
        "future-data leakage",
        "mae",
        "rmse",
        "wape",
        "predicted - actual",
        "last value",
        "historical mean",
        "historical median",
        "moving average",
        "seasonal naïve",
        "drift",
        "complex model is not preferred",
        "add no database table",
    ):
        assert statement in content


def test_phase_document_freezes_features_and_model_candidate_boundaries() -> None:
    content = _IMPLEMENTATION_DOCUMENT.read_text(encoding="utf-8").lower()
    for statement in (
        "checkpoint 9.6",
        "checkpoint 9.7",
        "checkpoint 9.8",
        "feature policy version `2026.1`",
        "target index",
        "lags 1, 7, 14, and 28",
        "monthly candidates use lags",
        "arima",
        "sarima",
        "prophet adapter is optional",
        "explicit unavailable-candidate",
        "four-decimal money",
        "random seed 2026",
        "recursive:",
        "no future actual value",
        "rank candidates",
        "automatic model selection",
        "uncertainty by checkpoint 9.10",
        "persistence by checkpoint 9.11",
    ):
        assert statement in content
