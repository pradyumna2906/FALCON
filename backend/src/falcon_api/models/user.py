"""User ownership root and financial-profile models."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from falcon_api.infrastructure.persistence import (
    Base,
    CurrencyCode,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
    UserStatus,
    enum_sql_values,
)
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from falcon_api.models.auth import (
        AuthenticationChallenge,
        AuthenticationDelivery,
        RefreshSession,
        UserCredential,
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Own every private financial record belonging to one person."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email = lower(email)",
            name="email_normalized",
        ),
        CheckConstraint(
            "length(trim(email)) >= 3",
            name="email_not_blank",
        ),
        CheckConstraint(
            f"status IN ({enum_sql_values(UserStatus)})",
            name="status_allowed",
        ),
        CheckConstraint(
            "default_currency ~ '^[A-Z]{3}$'",
            name="default_currency_iso",
        ),
        CheckConstraint(
            (
                "email_verified_at IS NULL OR "
                "email_verified_at >= created_at"
            ),
            name="email_verification_not_before_creation",
        ),
    )

    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
    )
    status: Mapped[UserStatus] = mapped_column(
        String(20),
        default=UserStatus.ACTIVE,
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        nullable=False,
    )
    default_currency: Mapped[CurrencyCode] = mapped_column(
        nullable=False,
    )
    email_verified_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )

    financial_profile: Mapped[FinancialProfile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    credential: Mapped[UserCredential | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    refresh_sessions: Mapped[list[RefreshSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    authentication_challenges: Mapped[
        list[AuthenticationChallenge]
    ] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    authentication_deliveries: Mapped[
        list[AuthenticationDelivery]
    ] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FinancialProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store the user's current financial-planning context."""

    __tablename__ = "financial_profiles"
    __table_args__ = (
        CheckConstraint(
            (
                "income_pattern IS NULL OR "
                f"income_pattern IN ({enum_sql_values(IncomePattern)})"
            ),
            name="income_pattern_allowed",
        ),
        CheckConstraint(
            (
                "income_stability IS NULL OR "
                f"income_stability IN ({enum_sql_values(IncomeStability)})"
            ),
            name="income_stability_allowed",
        ),
        CheckConstraint(
            (
                "completion_status IN "
                f"({enum_sql_values(ProfileCompletionStatus)})"
            ),
            name="completion_status_allowed",
        ),
        CheckConstraint(
            "dependant_count >= 0",
            name="dependant_count_non_negative",
        ),
        CheckConstraint(
            (
                "emergency_fund_target_months IS NULL OR "
                "emergency_fund_target_months >= 0"
            ),
            name="emergency_fund_target_non_negative",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_financial_profiles_user_id_users",
        ),
        nullable=False,
        unique=True,
    )
    income_pattern: Mapped[IncomePattern | None] = mapped_column(
        String(24),
        nullable=True,
    )
    income_stability: Mapped[IncomeStability | None] = mapped_column(
        String(16),
        nullable=True,
    )
    has_household_responsibilities: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    dependant_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    emergency_fund_target_months: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2, asdecimal=True),
        nullable=True,
    )
    completion_status: Mapped[ProfileCompletionStatus] = mapped_column(
        String(16),
        default=ProfileCompletionStatus.DRAFT,
        nullable=False,
    )

    user: Mapped[User] = relationship(
        back_populates="financial_profile",
    )
