"""Financial account and liability-detail models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from falcon_api.infrastructure.persistence import (
    MONEY_PRECISION,
    MONEY_SCALE,
    RATE_PRECISION,
    RATE_SCALE,
    Base,
    CurrencyCode,
    MoneyAmount,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)
from falcon_api.models.enums import (
    AccountType,
    LiabilitySubtype,
    enum_sql_values,
)
from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Account(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Represent one user-owned financial location or obligation."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "id",
            name="uq_accounts_user_id_id",
        ),
        UniqueConstraint(
            "user_id",
            "name",
            name="uq_accounts_user_name",
        ),
        CheckConstraint(
            f"account_type IN ({enum_sql_values(AccountType)})",
            name="account_type_allowed",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="currency_iso",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="name_not_blank",
        ),
        Index(
            "ix_accounts_user_active",
            "user_id",
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "ix_accounts_user_type",
            "user_id",
            "account_type",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_accounts_user_id_users",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    account_type: Mapped[AccountType] = mapped_column(
        String(24),
        nullable=False,
    )
    institution_name: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    masked_reference: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    currency: Mapped[CurrencyCode] = mapped_column(
        nullable=False,
    )
    opening_balance: Mapped[MoneyAmount] = mapped_column(
        default=Decimal("0"),
        nullable=False,
    )
    opening_balance_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    archived_at: Mapped[UTCDateTime | None] = mapped_column(
        nullable=True,
    )

    liability_detail: Mapped[LiabilityDetail | None] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class LiabilityDetail(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store terms specific to one debt-bearing account."""

    __tablename__ = "liability_details"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_liability_details_owner_account",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "account_id",
            name="uq_liability_details_account_id",
        ),
        CheckConstraint(
            (
                "liability_subtype IN "
                f"({enum_sql_values(LiabilitySubtype)})"
            ),
            name="liability_subtype_allowed",
        ),
        CheckConstraint(
            "principal_amount IS NULL OR principal_amount >= 0",
            name="principal_non_negative",
        ),
        CheckConstraint(
            "outstanding_amount IS NULL OR outstanding_amount >= 0",
            name="outstanding_non_negative",
        ),
        CheckConstraint(
            (
                "annual_interest_rate IS NULL OR "
                "(annual_interest_rate >= 0 AND annual_interest_rate <= 1)"
            ),
            name="annual_interest_rate_range",
        ),
        CheckConstraint(
            "minimum_payment IS NULL OR minimum_payment >= 0",
            name="minimum_payment_non_negative",
        ),
        CheckConstraint(
            "payment_due_day IS NULL OR payment_due_day BETWEEN 1 AND 31",
            name="payment_due_day_range",
        ),
        CheckConstraint(
            (
                "maturity_date IS NULL OR start_date IS NULL OR "
                "maturity_date >= start_date"
            ),
            name="maturity_not_before_start",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        nullable=False,
    )
    liability_subtype: Mapped[LiabilitySubtype] = mapped_column(
        String(24),
        nullable=False,
    )
    principal_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True),
        nullable=True,
    )
    outstanding_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True),
        nullable=True,
    )
    annual_interest_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(RATE_PRECISION, RATE_SCALE, asdecimal=True),
        nullable=True,
    )
    minimum_payment: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True),
        nullable=True,
    )
    payment_due_day: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    start_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    maturity_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    account: Mapped[Account] = relationship(
        back_populates="liability_detail",
    )
