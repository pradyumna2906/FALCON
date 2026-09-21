"""Owner- and cutoff-scoped forecast reads for Phase 11 evidence."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from falcon_api.forecasting.semantics import ForecastGranularity, ForecastTarget
from falcon_api.models.forecasting import ForecastRun


class ScenarioForecastRepository:
    """Load a matching forecast that existed at the source plan cutoff."""

    async def latest_eligible(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        target: ForecastTarget,
        cutoff_at: datetime,
        periods: tuple[date, ...],
    ) -> ForecastRun | None:
        resolved_target = ForecastTarget(target)
        if resolved_target not in {
            ForecastTarget.GROSS_INCOME,
            ForecastTarget.TOTAL_EXPENSE,
        }:
            raise ValueError("Scenario supplemental forecast target is invalid.")
        if cutoff_at.tzinfo is None or cutoff_at.utcoffset() is None:
            raise ValueError("Scenario forecast cutoffs must be timezone-aware.")
        if not periods:
            return None
        if periods != tuple(sorted(set(periods))) or any(
            item.day != 1 for item in periods
        ):
            raise ValueError("Scenario forecast periods must be ordered month boundaries.")
        statement = (
            select(ForecastRun)
            .options(selectinload(ForecastRun.points))
            .where(
                ForecastRun.user_id == user_id,
                ForecastRun.currency == currency,
                ForecastRun.target == resolved_target.value,
                ForecastRun.granularity == ForecastGranularity.MONTH.value,
                ForecastRun.data_cutoff_at <= cutoff_at,
                ForecastRun.created_at <= cutoff_at,
                or_(
                    ForecastRun.source_last_updated_at.is_(None),
                    ForecastRun.source_last_updated_at <= cutoff_at,
                ),
                ForecastRun.forecast_start == periods[0],
                ForecastRun.forecast_end == periods[-1],
                ForecastRun.horizon == len(periods),
            )
            .order_by(ForecastRun.created_at.desc(), ForecastRun.id.desc())
            .limit(1)
        )
        return await session.scalar(statement)
