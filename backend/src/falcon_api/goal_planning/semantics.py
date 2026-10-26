"""Versioned goal-management meanings and lifecycle boundaries."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from falcon_api.models.enums import GoalStatus


GOAL_PLANNING_CONTRACT_VERSION = "2026.1"
MAX_GOAL_LIST_LIMIT = 100


class GoalPlanningErrorCode(StrEnum):
    """Stable application failures owned by the Phase 10 boundary."""

    INVALID_CURRENCY = "goal_invalid_currency"
    INVALID_NAME = "goal_invalid_name"
    INVALID_DEADLINE = "goal_invalid_deadline"
    INVALID_AMOUNT = "goal_invalid_amount"
    INVALID_CONTRIBUTION = "goal_invalid_contribution"
    CONTRIBUTION_NOT_FOUND = "goal_contribution_not_found"
    CONTRIBUTION_EXCEEDS_REMAINING = "goal_contribution_exceeds_remaining"
    TRANSACTION_OVERALLOCATED = "goal_transaction_overallocated"
    CURRENCY_MISMATCH = "goal_currency_mismatch"
    SNAPSHOT_UNAVAILABLE = "goal_snapshot_unavailable"
    NOT_FOUND = "goal_not_found"
    INACTIVE = "goal_inactive"


def normalize_goal_currency(value: str) -> str:
    """Return one uppercase ISO-style currency without conversion."""
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError(GoalPlanningErrorCode.INVALID_CURRENCY.value)
    return normalized


def trusted_local_date(*, instant: datetime, timezone: str) -> date:
    """Resolve an aware cutoff into the authenticated user's local date."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Goal planning requires a timezone-aware cutoff.")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("Goal planning requires a trusted IANA timezone.") from None
    return instant.astimezone(zone).date()


def goal_status_can_transition(*, current: GoalStatus, target: GoalStatus) -> bool:
    """Allow one terminal transition from an active goal."""
    resolved_current = GoalStatus(current)
    resolved_target = GoalStatus(target)
    return resolved_current is GoalStatus.ACTIVE and resolved_target in {
        GoalStatus.COMPLETED,
        GoalStatus.CANCELLED,
    }
