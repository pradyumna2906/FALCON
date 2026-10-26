"""Establish the initial empty FALCON migration baseline."""

from collections.abc import Sequence


revision: str = "25efb498276a"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish the baseline without creating domain tables."""


def downgrade() -> None:
    """Remove the baseline without dropping domain tables."""
