"""Budget and financial-goal planning models."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from falcon_api.infrastructure.persistence import (
    MONEY_PRECISION,
    MONEY_SCALE,
    Base,
    CurrencyCode,
    MoneyAmount,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.category import Category
from falcon_api.models.enums import (
    ContributionSourceType,
    GoalPriority,
    GoalStatus,
    GoalType,
    enum_sql_values,
)
from falcon_api.models.ledger import Transaction
from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Budget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one user-owned spending plan for a bounded period."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_budgets_user_id_id",
        ),
        UniqueConstraint(
            "user_id",
            "name",
            "period_start_date",
            "period_end_date",
            name="uq_budgets_user_name_period",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="name_not_blank",
        ),
        CheckConstraint(
            "period_end_date >= period_start_date",
            name="period_valid",
        ),
        CheckConstraint(
            "overall_limit IS NULL OR overall_limit > 0",
            name="overall_limit_positive",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="currency_iso",
        ),
        Index(
            "ix_budgets_user_active_period",
            "user_id",
            "period_start_date",
            "period_end_date",
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_budgets_user_id_users",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    period_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    period_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    currency: Mapped[CurrencyCode] = mapped_column(
        nullable=False,
    )
    overall_limit: Mapped[MoneyAmount | None] = mapped_column(
        nullable=True,
    )
    archived_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )

    limits: Mapped[list[BudgetLimit]] = relationship(
        back_populates="budget",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class BudgetLimit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Assign one positive expense-category limit within a budget."""

    __tablename__ = "budget_limits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_budget_limits_user_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "budget_id"],
            ["budgets.user_id", "budgets.id"],
            name="fk_budget_limits_owner_budget",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "budget_id",
            "category_id",
            name="uq_budget_limits_budget_category",
        ),
        CheckConstraint(
            "limit_amount > 0",
            name="limit_amount_positive",
        ),
        Index(
            "ix_budget_limits_category",
            "category_id",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    budget_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "categories.id",
            ondelete="RESTRICT",
            name="fk_budget_limits_category_id_categories",
        ),
        nullable=False,
    )
    limit_amount: Mapped[MoneyAmount] = mapped_column(
        nullable=False,
    )

    budget: Mapped[Budget] = relationship(
        back_populates="limits",
    )
    category: Mapped[Category] = relationship()


class Goal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one user-owned financial target."""

    __tablename__ = "goals"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_goals_user_id_id",
        ),
        CheckConstraint(
            f"goal_type IN ({enum_sql_values(GoalType)})",
            name="goal_type_allowed",
        ),
        CheckConstraint(
            f"priority IN ({enum_sql_values(GoalPriority)})",
            name="priority_allowed",
        ),
        CheckConstraint(
            f"status IN ({enum_sql_values(GoalStatus)})",
            name="status_allowed",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="name_not_blank",
        ),
        CheckConstraint(
            "target_amount > 0",
            name="target_amount_positive",
        ),
        CheckConstraint(
            "starting_amount >= 0",
            name="starting_amount_non_negative",
        ),
        CheckConstraint(
            "starting_amount <= target_amount",
            name="starting_not_above_target",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="currency_iso",
        ),
        Index(
            "ix_goals_user_status_deadline",
            "user_id",
            "status",
            "target_date",
        ),
        Index(
            "ix_goals_user_priority_deadline",
            "user_id",
            "priority",
            "target_date",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_goals_user_id_users",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    goal_type: Mapped[GoalType] = mapped_column(
        String(24),
        nullable=False,
    )
    target_amount: Mapped[MoneyAmount] = mapped_column(
        nullable=False,
    )
    starting_amount: Mapped[MoneyAmount] = mapped_column(
        nullable=False,
    )
    currency: Mapped[CurrencyCode] = mapped_column(
        nullable=False,
    )
    target_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    priority: Mapped[GoalPriority] = mapped_column(
        String(16),
        nullable=False,
    )
    status: Mapped[GoalStatus] = mapped_column(
        String(16),
        default=GoalStatus.ACTIVE,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    contributions: Mapped[list[GoalContribution]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        overlaps="transaction",
        passive_deletes=True,
    )


class GoalContribution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one positive allocation toward a financial goal."""

    __tablename__ = "goal_contributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_goal_contributions_user_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "goal_id"],
            ["goals.user_id", "goals.id"],
            name="fk_goal_contributions_owner_goal",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "transaction_id"],
            ["transactions.user_id", "transactions.id"],
            name="fk_goal_contributions_owner_transaction",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "amount > 0",
            name="amount_positive",
        ),
        CheckConstraint(
            (
                "source_type IN "
                f"({enum_sql_values(ContributionSourceType)})"
            ),
            name="source_type_allowed",
        ),
        CheckConstraint(
            (
                "(source_type = 'transaction' "
                "AND transaction_id IS NOT NULL) OR "
                "(source_type <> 'transaction' "
                "AND transaction_id IS NULL)"
            ),
            name="transaction_source_consistent",
        ),
        Index(
            "ix_goal_contributions_goal_date",
            "goal_id",
            "contribution_date",
        ),
        Index(
            "ix_goal_contributions_transaction",
            "transaction_id",
            postgresql_where=text("transaction_id IS NOT NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    goal_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    transaction_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
    )
    amount: Mapped[MoneyAmount] = mapped_column(
        nullable=False,
    )
    contribution_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    source_type: Mapped[ContributionSourceType] = mapped_column(
        String(24),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    goal: Mapped[Goal] = relationship(
        back_populates="contributions",
        overlaps="transaction",
    )
    transaction: Mapped[Transaction | None] = relationship(
        overlaps="contributions,goal",
    )
