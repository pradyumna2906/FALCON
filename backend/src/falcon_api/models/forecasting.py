"""Immutable owner-scoped forecast runs and point estimates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from falcon_api.infrastructure.persistence import (
    Base,
    CurrencyCode,
    MoneyAmount,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
)


class ForecastRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store one immutable forecast decision with complete policy provenance."""

    __tablename__ = "forecast_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_forecast_runs_user_id_id"),
        CheckConstraint(
            "target IN ('gross_income', 'total_expense', 'net_cash_flow', "
            "'savings_amount')",
            name="target_allowed",
        ),
        CheckConstraint(
            "granularity IN ('day', 'month')",
            name="granularity_allowed",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint("history_end >= history_start", name="history_valid"),
        CheckConstraint("forecast_end >= forecast_start", name="forecast_valid"),
        CheckConstraint("horizon > 0", name="horizon_positive"),
        CheckConstraint(
            "selection_metric IN ('wape', 'mae')",
            name="selection_metric_allowed",
        ),
        CheckConstraint(
            "uncertainty_reliability IN ('provisional', 'normal')",
            name="uncertainty_reliability_allowed",
        ),
        CheckConstraint(
            "validation_mae >= 0 AND validation_rmse >= 0 AND "
            "(validation_wape IS NULL OR validation_wape >= 0)",
            name="validation_metrics_non_negative",
        ),
        CheckConstraint(
            "test_mae >= 0 AND test_rmse >= 0 AND "
            "(test_wape IS NULL OR test_wape >= 0)",
            name="test_metrics_non_negative",
        ),
        CheckConstraint(
            "length(trim(model_code)) > 0 AND length(trim(model_version)) > 0",
            name="model_identity_not_blank",
        ),
        CheckConstraint(
            "jsonb_typeof(model_parameters) = 'object' AND "
            "jsonb_typeof(candidate_evidence) = 'object'",
            name="evidence_objects",
        ),
        Index(
            "ix_forecast_runs_user_target_created",
            "user_id",
            "target",
            "created_at",
        ),
        Index(
            "ix_forecast_runs_user_currency_created",
            "user_id",
            "currency",
            "created_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_forecast_runs_user_id_users",
        ),
        nullable=False,
    )
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    granularity: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[CurrencyCode] = mapped_column(nullable=False)
    history_start: Mapped[date] = mapped_column(Date, nullable=False)
    history_end: Mapped[date] = mapped_column(Date, nullable=False)
    data_cutoff_at: Mapped[UTCDateTime] = mapped_column(nullable=False)
    source_last_updated_at: Mapped[UTCDateTime | None] = mapped_column(nullable=True)
    forecast_start: Mapped[date] = mapped_column(Date, nullable=False)
    forecast_end: Mapped[date] = mapped_column(Date, nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    selection_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    uncertainty_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_code: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    candidate_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    selection_metric: Mapped[str] = mapped_column(String(8), nullable=False)
    validation_mae: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    validation_rmse: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    validation_wape: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    validation_bias: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    test_mae: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    test_rmse: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    test_wape: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    test_bias: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    uncertainty_method: Mapped[str] = mapped_column(String(64), nullable=False)
    uncertainty_reliability: Mapped[str] = mapped_column(String(16), nullable=False)

    points: Mapped[list[ForecastPoint]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ForecastPoint.step",
    )


class ForecastPoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Store one immutable expected value with nested 80% and 95% bands."""

    __tablename__ = "forecast_points"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "forecast_run_id"],
            ["forecast_runs.user_id", "forecast_runs.id"],
            name="fk_forecast_points_owner_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "forecast_run_id",
            "step",
            name="uq_forecast_points_run_step",
        ),
        UniqueConstraint(
            "forecast_run_id",
            "period_start",
            name="uq_forecast_points_run_period",
        ),
        CheckConstraint("step > 0", name="step_positive"),
        CheckConstraint(
            "lower_95 <= lower_80 AND lower_80 <= expected_value AND "
            "expected_value <= upper_80 AND upper_80 <= upper_95",
            name="bands_nested",
        ),
        Index(
            "ix_forecast_points_user_run_step",
            "user_id",
            "forecast_run_id",
            "step",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    forecast_run_id: Mapped[UUID] = mapped_column(nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    expected_value: Mapped[MoneyAmount] = mapped_column(nullable=False)
    lower_80: Mapped[MoneyAmount] = mapped_column(nullable=False)
    upper_80: Mapped[MoneyAmount] = mapped_column(nullable=False)
    lower_95: Mapped[MoneyAmount] = mapped_column(nullable=False)
    upper_95: Mapped[MoneyAmount] = mapped_column(nullable=False)

    run: Mapped[ForecastRun] = relationship(back_populates="points")
