"""Strict authenticated API contracts for cognitive forecasting."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from falcon_api.forecasting.semantics import (
    MAX_DAILY_FORECAST_HORIZON,
    MAX_MONTHLY_FORECAST_HORIZON,
    ForecastGranularity,
    ForecastTarget,
)


CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$"),
]
MoneyValue = Annotated[Decimal, Field(max_digits=19, decimal_places=4)]


class ForecastSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class ForecastGenerationRequest(ForecastSchema):
    target: ForecastTarget
    granularity: ForecastGranularity = ForecastGranularity.MONTH
    currency: CurrencyCode | None = None
    history_start: date
    history_end: date
    horizon: int = Field(ge=1, le=MAX_DAILY_FORECAST_HORIZON)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_window_and_horizon(self) -> "ForecastGenerationRequest":
        if self.history_end < self.history_start:
            raise ValueError("Forecast history end cannot precede its start.")
        if (
            self.granularity is ForecastGranularity.MONTH
            and self.horizon > MAX_MONTHLY_FORECAST_HORIZON
        ):
            raise ValueError("Monthly forecast horizon cannot exceed 24 periods.")
        return self


class ForecastPointResponse(ForecastSchema):
    step: int
    period_start: date
    expected_value: MoneyValue
    lower_80: MoneyValue
    upper_80: MoneyValue
    lower_95: MoneyValue
    upper_95: MoneyValue


class ForecastRunSummaryResponse(ForecastSchema):
    id: UUID
    created_at: datetime
    target: ForecastTarget
    granularity: ForecastGranularity
    currency: str
    forecast_start: date
    forecast_end: date
    horizon: int
    model_code: str
    uncertainty_reliability: str


class ForecastRunResponse(ForecastRunSummaryResponse):
    history_start: date
    history_end: date
    data_cutoff_at: datetime
    source_last_updated_at: datetime | None
    contract_version: str
    quality_policy_version: str
    evaluation_policy_version: str
    feature_policy_version: str | None
    selection_policy_version: str
    uncertainty_policy_version: str
    model_version: str
    model_parameters: dict[str, Any]
    candidate_evidence: dict[str, Any]
    selection_metric: str
    validation_mae: Decimal
    validation_rmse: Decimal
    validation_wape: Decimal | None
    validation_bias: Decimal
    test_mae: Decimal
    test_rmse: Decimal
    test_wape: Decimal | None
    test_bias: Decimal
    uncertainty_method: str
    points: tuple[ForecastPointResponse, ...]


class ForecastRunListResponse(ForecastSchema):
    items: tuple[ForecastRunSummaryResponse, ...]
