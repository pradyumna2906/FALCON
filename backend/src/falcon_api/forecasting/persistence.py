"""Owner-scoped persistence for immutable forecast decisions and points."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from falcon_api.forecasting.semantics import (
    ForecastGranularity,
    ForecastTarget,
    normalize_forecast_currency,
)
from falcon_api.models.forecasting import ForecastPoint, ForecastRun


MAX_FORECAST_EVIDENCE_BYTES = 32_768
_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "account_number",
        "description",
        "email",
        "merchant",
        "raw_transactions",
        "raw_values",
        "transaction_ids",
        "user_id",
    }
)


@dataclass(frozen=True, slots=True)
class ForecastPointWrite:
    step: int
    period_start: date
    expected_value: Decimal
    lower_80: Decimal
    upper_80: Decimal
    lower_95: Decimal
    upper_95: Decimal

    def __post_init__(self) -> None:
        values = (
            self.expected_value,
            self.lower_80,
            self.upper_80,
            self.lower_95,
            self.upper_95,
        )
        if isinstance(self.step, bool) or self.step <= 0:
            raise ValueError("Forecast point step must be positive.")
        if any(not value.is_finite() for value in values):
            raise ValueError("Forecast point values must be finite.")
        if not (
            self.lower_95
            <= self.lower_80
            <= self.expected_value
            <= self.upper_80
            <= self.upper_95
        ):
            raise ValueError("Forecast confidence bands must be nested.")


@dataclass(frozen=True, slots=True)
class ForecastRunWrite:
    target: ForecastTarget
    granularity: ForecastGranularity
    currency: str
    history_start: date
    history_end: date
    data_cutoff_at: datetime
    source_last_updated_at: datetime | None
    forecast_start: date
    forecast_end: date
    contract_version: str
    quality_policy_version: str
    evaluation_policy_version: str
    feature_policy_version: str | None
    selection_policy_version: str
    uncertainty_policy_version: str
    model_code: str
    model_version: str
    model_parameters: Mapping[str, object]
    candidate_evidence: Mapping[str, object]
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
    uncertainty_reliability: str
    points: tuple[ForecastPointWrite, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", ForecastTarget(self.target))
        object.__setattr__(self, "granularity", ForecastGranularity(self.granularity))
        object.__setattr__(self, "currency", normalize_forecast_currency(self.currency))
        if not self.points:
            raise ValueError("Forecast persistence requires at least one point.")
        if self.history_end < self.history_start:
            raise ValueError("Forecast history range is invalid.")
        if self.forecast_end < self.forecast_start:
            raise ValueError("Forecast output range is invalid.")
        if self.data_cutoff_at.tzinfo is None or self.data_cutoff_at.utcoffset() is None:
            raise ValueError("Forecast data cutoff must be timezone-aware.")
        if self.source_last_updated_at is not None and (
            self.source_last_updated_at.tzinfo is None
            or self.source_last_updated_at.utcoffset() is None
        ):
            raise ValueError("Forecast source timestamp must be timezone-aware.")
        if (
            self.source_last_updated_at is not None
            and self.source_last_updated_at > self.data_cutoff_at
        ):
            raise ValueError("Forecast source timestamp cannot exceed its cutoff.")
        if self.forecast_start <= self.history_end:
            raise ValueError("Forecast output must begin after complete history.")
        versions = (
            self.contract_version,
            self.quality_policy_version,
            self.evaluation_policy_version,
            self.selection_policy_version,
            self.uncertainty_policy_version,
            self.model_code,
            self.model_version,
            self.uncertainty_method,
        )
        if any(not value.strip() for value in versions):
            raise ValueError("Forecast policy and model identities cannot be blank.")
        if self.feature_policy_version is not None and not self.feature_policy_version.strip():
            raise ValueError("Feature policy version cannot be blank.")
        if self.selection_metric not in {"wape", "mae"}:
            raise ValueError("Forecast selection metric is invalid.")
        if self.uncertainty_reliability not in {"provisional", "normal"}:
            raise ValueError("Forecast uncertainty reliability is invalid.")
        metrics = (
            self.validation_mae,
            self.validation_rmse,
            self.validation_wape,
            self.validation_bias,
            self.test_mae,
            self.test_rmse,
            self.test_wape,
            self.test_bias,
        )
        if any(value is not None and not value.is_finite() for value in metrics):
            raise ValueError("Forecast evaluation metrics must be finite.")
        if any(
            value is not None and value < 0
            for value in (
                self.validation_mae,
                self.validation_rmse,
                self.validation_wape,
                self.test_mae,
                self.test_rmse,
                self.test_wape,
            )
        ):
            raise ValueError("Forecast error magnitudes cannot be negative.")
        expected_steps = tuple(range(1, len(self.points) + 1))
        if tuple(point.step for point in self.points) != expected_steps:
            raise ValueError("Forecast point steps must be contiguous and ordered.")
        periods = tuple(point.period_start for point in self.points)
        if periods != tuple(sorted(set(periods))):
            raise ValueError("Forecast point periods must be unique and ordered.")
        expected_periods = _period_sequence(
            start=self.forecast_start,
            count=len(self.points),
            granularity=self.granularity,
        )
        if periods != expected_periods or self.forecast_end != periods[-1]:
            raise ValueError("Forecast points must exactly match the declared horizon.")
        parameters = _validated_evidence_object(
            self.model_parameters,
            label="model parameters",
        )
        evidence = _validated_evidence_object(
            self.candidate_evidence,
            label="candidate evidence",
        )
        object.__setattr__(self, "model_parameters", parameters)
        object.__setattr__(self, "candidate_evidence", evidence)


class ForecastPersistenceRepository:
    """Create and read forecast records only through an authenticated owner."""

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        payload: ForecastRunWrite,
    ) -> ForecastRun:
        run_id = uuid4()
        run = ForecastRun(
            id=run_id,
            user_id=user_id,
            target=payload.target.value,
            granularity=payload.granularity.value,
            currency=payload.currency,
            history_start=payload.history_start,
            history_end=payload.history_end,
            data_cutoff_at=payload.data_cutoff_at,
            source_last_updated_at=payload.source_last_updated_at,
            forecast_start=payload.forecast_start,
            forecast_end=payload.forecast_end,
            horizon=len(payload.points),
            contract_version=payload.contract_version,
            quality_policy_version=payload.quality_policy_version,
            evaluation_policy_version=payload.evaluation_policy_version,
            feature_policy_version=payload.feature_policy_version,
            selection_policy_version=payload.selection_policy_version,
            uncertainty_policy_version=payload.uncertainty_policy_version,
            model_code=payload.model_code,
            model_version=payload.model_version,
            model_parameters=dict(payload.model_parameters),
            candidate_evidence=dict(payload.candidate_evidence),
            selection_metric=payload.selection_metric,
            validation_mae=payload.validation_mae,
            validation_rmse=payload.validation_rmse,
            validation_wape=payload.validation_wape,
            validation_bias=payload.validation_bias,
            test_mae=payload.test_mae,
            test_rmse=payload.test_rmse,
            test_wape=payload.test_wape,
            test_bias=payload.test_bias,
            uncertainty_method=payload.uncertainty_method,
            uncertainty_reliability=payload.uncertainty_reliability,
            points=[
                ForecastPoint(
                    user_id=user_id,
                    forecast_run_id=run_id,
                    step=point.step,
                    period_start=point.period_start,
                    expected_value=point.expected_value,
                    lower_80=point.lower_80,
                    upper_80=point.upper_80,
                    lower_95=point.lower_95,
                    upper_95=point.upper_95,
                )
                for point in payload.points
            ],
        )
        session.add(run)
        await session.flush()
        return run

    async def get(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        run_id: UUID,
    ) -> ForecastRun | None:
        statement = (
            select(ForecastRun)
            .options(selectinload(ForecastRun.points))
            .where(ForecastRun.user_id == user_id, ForecastRun.id == run_id)
        )
        return await session.scalar(statement)

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        limit: int,
    ) -> tuple[ForecastRun, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("Forecast history limit must be between 1 and 100.")
        statement = (
            select(ForecastRun)
            .where(ForecastRun.user_id == user_id)
            .order_by(ForecastRun.created_at.desc(), ForecastRun.id.desc())
            .limit(limit)
        )
        rows = await session.scalars(statement)
        return tuple(rows.all())


def _period_sequence(
    *,
    start: date,
    count: int,
    granularity: ForecastGranularity,
) -> tuple[date, ...]:
    periods: list[date] = []
    current = start
    for _ in range(count):
        periods.append(current)
        if granularity is ForecastGranularity.DAY:
            current += timedelta(days=1)
        else:
            if current.day != 1:
                raise ValueError("Monthly forecast points must start on month boundaries.")
            year = current.year + (1 if current.month == 12 else 0)
            month = 1 if current.month == 12 else current.month + 1
            current = date(year, month, 1)
    return tuple(periods)


def _validated_evidence_object(
    value: Mapping[str, object], *, label: str
) -> dict[str, object]:
    normalized = dict(value)

    def inspect(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"Forecast {label} keys must be strings.")
                if key.strip().lower() in _FORBIDDEN_EVIDENCE_KEYS:
                    raise ValueError(f"Forecast {label} cannot contain raw personal data.")
                inspect(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                inspect(nested)

    inspect(normalized)
    try:
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Forecast {label} must be JSON serializable.") from exc
    if len(encoded.encode("utf-8")) > MAX_FORECAST_EVIDENCE_BYTES:
        raise ValueError(f"Forecast {label} exceeds the persistence limit.")
    return normalized
