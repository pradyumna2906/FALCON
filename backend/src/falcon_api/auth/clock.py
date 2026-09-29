"""UTC clock abstractions used by authentication services."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Provide the current timezone-aware UTC timestamp."""

    def now(self) -> datetime:
        """Return the current time in UTC."""


class SystemClock:
    """Production clock backed by the system time."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC timestamp."""
        return datetime.now(UTC)
