"""Versioned Phase 10 contract and boundary tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from falcon_api.goal_planning import (
    GOAL_PLANNING_CONTRACT_VERSION,
    MAX_GOAL_LIST_LIMIT,
    goal_status_can_transition,
    normalize_goal_currency,
    trusted_local_date,
)
from falcon_api.models.enums import GoalStatus


def test_goal_contract_has_stable_version_and_limit() -> None:
    assert GOAL_PLANNING_CONTRACT_VERSION == "2026.1"
    assert MAX_GOAL_LIST_LIMIT == 100


def test_batch_1_documentation_freezes_scope_and_deferrals() -> None:
    document = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "goals"
        / "PHASE_10_IMPLEMENTATION.md"
    ).read_text(encoding="utf-8")

    assert "Goal-planning contract version: `2026.1`" in document
    assert "Checkpoints 10.0, 10.1, and 10.2" in document
    assert "Batch 1 adds no contribution service" in document
    assert "Phase 11 owns" in document


def test_currency_is_normalized_without_conversion() -> None:
    assert normalize_goal_currency(" inr ") == "INR"


@pytest.mark.parametrize("value", ["", "RUPEE", "12R", "₹₹₹", "US$"])
def test_invalid_currency_fails_closed(value: str) -> None:
    with pytest.raises(ValueError, match="goal_invalid_currency"):
        normalize_goal_currency(value)


def test_trusted_cutoff_resolves_to_principal_local_date() -> None:
    instant = datetime(2026, 9, 14, 20, tzinfo=UTC)
    assert str(trusted_local_date(instant=instant, timezone="Asia/Kolkata")) == (
        "2026-09-15"
    )


def test_trusted_cutoff_rejects_naive_time_and_unknown_zone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        trusted_local_date(
            instant=datetime(2026, 9, 14),
            timezone="Asia/Kolkata",
        )
    with pytest.raises(ValueError, match="trusted IANA"):
        trusted_local_date(
            instant=datetime(2026, 9, 14, tzinfo=UTC),
            timezone="Mars/Olympus",
        )


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (GoalStatus.ACTIVE, GoalStatus.COMPLETED, True),
        (GoalStatus.ACTIVE, GoalStatus.CANCELLED, True),
        (GoalStatus.ACTIVE, GoalStatus.ACTIVE, False),
        (GoalStatus.COMPLETED, GoalStatus.CANCELLED, False),
        (GoalStatus.CANCELLED, GoalStatus.COMPLETED, False),
    ],
)
def test_only_active_to_terminal_transitions_are_allowed(
    current: GoalStatus,
    target: GoalStatus,
    allowed: bool,
) -> None:
    assert goal_status_can_transition(current=current, target=target) is allowed
