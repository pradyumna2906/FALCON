"""End-to-end owner-scoped forecast generation orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.core.errors import ApplicationError
from falcon_api.forecasting.baselines import baseline_candidates
from falcon_api.forecasting.boosting import XGBoostCandidate
from falcon_api.forecasting.candidates import ForecastCandidateFitError
from falcon_api.forecasting.evaluation import (
    FORECAST_EVALUATION_POLICY_VERSION,
    ForecastCandidate,
    RollingOriginConfig,
    build_chronological_evaluation_plan,
)
from falcon_api.forecasting.features import FORECAST_FEATURE_POLICY_VERSION
from falcon_api.forecasting.monitoring import ForecastMonitor
from falcon_api.forecasting.periods import ForecastHistoryWindow
from falcon_api.forecasting.persistence import (
    ForecastPersistenceRepository,
    ForecastPointWrite,
    ForecastRunWrite,
)
from falcon_api.forecasting.quality import (
    FORECAST_QUALITY_POLICY_VERSION,
    ForecastEligibility,
    assess_forecast_quality,
)
from falcon_api.forecasting.repository import ForecastingRepository
from falcon_api.forecasting.semantics import (
    FORECASTING_CONTRACT_VERSION,
    ForecastGranularity,
    ForecastTarget,
    normalize_forecast_currency,
    validate_forecast_horizon,
)
from falcon_api.forecasting.selection import select_forecast_model
from falcon_api.forecasting.series import build_forecast_series
from falcon_api.forecasting.statistical import (
    ArimaCandidate,
    ProphetCandidate,
    SarimaCandidate,
)
from falcon_api.forecasting.uncertainty import (
    calibrate_forecast_uncertainty,
    build_forecast_uncertainty,
)
from falcon_api.models.forecasting import ForecastRun


CandidateFactory = Callable[[ForecastGranularity], tuple[ForecastCandidate, ...]]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ForecastGenerationCommand:
    target: ForecastTarget
    granularity: ForecastGranularity
    currency: str
    history_start: date
    history_end: date
    horizon: int
    trusted_timezone: str


class FinancialForecastService:
    """Build, evaluate, persist, and retrieve immutable owner forecasts."""

    def __init__(
        self,
        *,
        source_repository: ForecastingRepository | None = None,
        persistence_repository: ForecastPersistenceRepository | None = None,
        candidate_factory: CandidateFactory | None = None,
        monitor: ForecastMonitor | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._source = source_repository or ForecastingRepository()
        self._persistence = persistence_repository or ForecastPersistenceRepository()
        self._candidates = candidate_factory or forecasting_candidates
        self._monitor = monitor or ForecastMonitor()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def generate(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        command: ForecastGenerationCommand,
    ) -> ForecastRun:
        started_at = self._monitor.start()
        target = ForecastTarget(command.target)
        granularity = ForecastGranularity(command.granularity)
        currency = normalize_forecast_currency(command.currency)
        horizon = validate_forecast_horizon(
            granularity=granularity,
            horizon=command.horizon,
        )
        window = ForecastHistoryWindow(
            date_from=command.history_start,
            date_to=command.history_end,
            timezone=command.trusted_timezone,
            granularity=granularity,
            data_cutoff_at=self._clock(),
        )
        buckets = await self._source.list_source_buckets(
            session,
            user_id=user_id,
            window=window,
            currency=currency,
        )
        series = build_forecast_series(
            target=target,
            currency=currency,
            window=window,
            buckets=buckets,
        )
        quality = assess_forecast_quality(series)
        if quality.eligibility is ForecastEligibility.UNAVAILABLE:
            raise ApplicationError(
                code="forecast_history_unavailable",
                message="No eligible transaction history is available for this forecast.",
                status_code=422,
            )
        values = tuple(point.value for point in series.points)
        try:
            plan = build_chronological_evaluation_plan(
                series_length=len(values),
                config=RollingOriginConfig(
                    minimum_training_points=1,
                    validation_horizon=1,
                    test_size=1,
                    maximum_folds=12,
                ),
            )
        except ValueError:
            raise ApplicationError(
                code="forecast_history_insufficient",
                message="More chronological history is required to evaluate a forecast.",
                status_code=422,
            ) from None

        candidates = self._candidates(granularity)
        try:
            selection = select_forecast_model(
                values=values,
                plan=plan,
                candidates=candidates,
            )
            selected_candidate = next(
                candidate
                for candidate in candidates
                if candidate.code == selection.selected_model_code
            )
            expected = selected_candidate.predict(values, horizon)
        except (ForecastCandidateFitError, StopIteration, ValueError):
            raise ApplicationError(
                code="forecast_model_unavailable",
                message="No safe forecasting model is available for this history.",
                status_code=422,
            ) from None

        selected_evaluation = next(
            evidence
            for evidence in selection.candidate_evaluations
            if evidence.model_code == selection.selected_model_code
        )
        calibration = calibrate_forecast_uncertainty(
            evaluation=selected_evaluation,
        )
        uncertain_points = build_forecast_uncertainty(
            expected=expected,
            calibration=calibration,
            floor_at_zero=target
            in {ForecastTarget.GROSS_INCOME, ForecastTarget.TOTAL_EXPENSE},
        )
        periods = _future_periods(
            history_end=series.history_end,
            granularity=granularity,
            count=horizon,
        )
        writes = tuple(
            _point_write(period=period, point=point)
            for period, point in zip(periods, uncertain_points)
        )
        validation = selected_evaluation.metrics
        final_test = selection.final_test.metrics
        persisted = await self._persistence.create(
            session,
            user_id=user_id,
            payload=ForecastRunWrite(
                target=target,
                granularity=granularity,
                currency=currency,
                history_start=series.history_start,
                history_end=series.history_end,
                data_cutoff_at=series.data_cutoff_at,
                source_last_updated_at=series.source_last_updated_at,
                forecast_start=periods[0],
                forecast_end=periods[-1],
                contract_version=FORECASTING_CONTRACT_VERSION,
                quality_policy_version=FORECAST_QUALITY_POLICY_VERSION,
                evaluation_policy_version=FORECAST_EVALUATION_POLICY_VERSION,
                feature_policy_version=(
                    FORECAST_FEATURE_POLICY_VERSION
                    if selected_candidate.code.startswith("xgboost_")
                    else None
                ),
                selection_policy_version=selection.policy_version,
                uncertainty_policy_version=calibration.policy_version,
                model_code=selected_candidate.code,
                model_version="adapter-2026.1",
                model_parameters=_model_parameters(selected_candidate),
                candidate_evidence={
                    "evaluated_models": [
                        evidence.model_code
                        for evidence in selection.candidate_evaluations
                    ],
                    "failed_models": [
                        {"model_code": failure.model_code, "reason": failure.reason.value}
                        for failure in selection.candidate_failures
                    ],
                    "quality_eligibility": quality.eligibility.value,
                    "quality_reasons": [reason.value for reason in quality.reasons],
                    "calibration_residual_count": calibration.residual_count,
                },
                selection_metric=selection.ranking_metric.value,
                validation_mae=validation.mae,
                validation_rmse=validation.rmse,
                validation_wape=validation.wape,
                validation_bias=validation.bias,
                test_mae=final_test.mae,
                test_rmse=final_test.rmse,
                test_wape=final_test.wape,
                test_bias=final_test.bias,
                uncertainty_method="absolute_residual_conformal",
                uncertainty_reliability=calibration.reliability.value,
                points=writes,
            ),
        )
        self._monitor.record_generation(
            started_at=started_at,
            target=target,
            granularity=granularity,
            history_periods=len(values),
            horizon=horizon,
            eligibility=quality.eligibility,
            candidate_count=len(candidates),
            failure_count=len(selection.candidate_failures),
            selected_model_code=selection.selected_model_code,
        )
        return persisted

    async def get(
        self, session: AsyncSession, *, user_id: UUID, run_id: UUID
    ) -> ForecastRun:
        run = await self._persistence.get(session, user_id=user_id, run_id=run_id)
        if run is None:
            raise ApplicationError(
                code="forecast_not_found",
                message="The requested forecast was not found.",
                status_code=404,
            )
        return run

    async def list_recent(
        self, session: AsyncSession, *, user_id: UUID, limit: int
    ) -> tuple[ForecastRun, ...]:
        return await self._persistence.list_recent(
            session, user_id=user_id, limit=limit
        )


def forecasting_candidates(
    granularity: ForecastGranularity,
) -> tuple[ForecastCandidate, ...]:
    resolved = ForecastGranularity(granularity)
    return cast(
        tuple[ForecastCandidate, ...],
        (
            *baseline_candidates(resolved),
            ArimaCandidate(),
            SarimaCandidate(resolved),
            ProphetCandidate(resolved),
            XGBoostCandidate(resolved),
        ),
    )


def _future_periods(
    *, history_end: date, granularity: ForecastGranularity, count: int
) -> tuple[date, ...]:
    if granularity is ForecastGranularity.DAY:
        return tuple(history_end + timedelta(days=step) for step in range(1, count + 1))
    year = history_end.year + (1 if history_end.month == 12 else 0)
    month = 1 if history_end.month == 12 else history_end.month + 1
    current = date(year, month, 1)
    periods: list[date] = []
    for _ in range(count):
        periods.append(current)
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)
    return tuple(periods)


def _point_write(*, period: date, point: object) -> ForecastPointWrite:
    from falcon_api.forecasting.uncertainty import ForecastPointUncertainty

    resolved = cast(ForecastPointUncertainty, point)
    bands = {band.confidence_level: band for band in resolved.bands}
    band_80 = bands[Decimal("0.800000")]
    band_95 = bands[Decimal("0.950000")]
    return ForecastPointWrite(
        step=resolved.step,
        period_start=period,
        expected_value=resolved.expected,
        lower_80=band_80.lower,
        upper_80=band_80.upper,
        lower_95=band_95.lower,
        upper_95=band_95.upper,
    )


def _model_parameters(candidate: ForecastCandidate) -> dict[str, object]:
    parameters: dict[str, object] = {}
    for name in (
        "order",
        "seasonal_order",
        "window",
        "season_length",
        "estimators",
        "maximum_depth",
        "learning_rate",
        "random_state",
    ):
        if hasattr(candidate, name):
            value = getattr(candidate, name)
            parameters[name] = list(value) if isinstance(value, tuple) else value
    return parameters
