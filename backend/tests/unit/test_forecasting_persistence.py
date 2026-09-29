"""Tests for immutable owner-scoped forecast persistence contracts."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.forecasting import (
    ForecastGranularity,
    ForecastPersistenceRepository,
    ForecastPointWrite,
    ForecastRunWrite,
    ForecastTarget,
)


def _point(step: int = 1, *, period: date = date(2026, 10, 1)) -> ForecastPointWrite:
    return ForecastPointWrite(
        step=step,
        period_start=period,
        expected_value=Decimal("100"),
        lower_80=Decimal("90"),
        upper_80=Decimal("110"),
        lower_95=Decimal("80"),
        upper_95=Decimal("120"),
    )


def _payload(points: tuple[ForecastPointWrite, ...] | None = None) -> ForecastRunWrite:
    return ForecastRunWrite(
        target=ForecastTarget.TOTAL_EXPENSE,
        granularity=ForecastGranularity.MONTH,
        currency="inr",
        history_start=date(2026, 1, 1),
        history_end=date(2026, 9, 30),
        data_cutoff_at=datetime(2026, 10, 1, tzinfo=UTC),
        source_last_updated_at=datetime(2026, 9, 30, tzinfo=UTC),
        forecast_start=date(2026, 10, 1),
        forecast_end=date(2026, 10, 1),
        contract_version="2026.1",
        quality_policy_version="2026.1",
        evaluation_policy_version="2026.1",
        feature_policy_version=None,
        selection_policy_version="2026.1",
        uncertainty_policy_version="2026.1",
        model_code="last_value",
        model_version="builtin-2026.1",
        model_parameters={},
        candidate_evidence={"evaluated": ["last_value"]},
        selection_metric="wape",
        validation_mae=Decimal("1"),
        validation_rmse=Decimal("1"),
        validation_wape=Decimal("0.1"),
        validation_bias=Decimal("0"),
        test_mae=Decimal("2"),
        test_rmse=Decimal("2"),
        test_wape=Decimal("0.2"),
        test_bias=Decimal("1"),
        uncertainty_method="absolute_residual_conformal",
        uncertainty_reliability="provisional",
        points=points if points is not None else (_point(),),
    )


def test_forecast_write_normalizes_currency_and_validates_points() -> None:
    payload = _payload()
    assert payload.currency == "INR"
    assert payload.target is ForecastTarget.TOTAL_EXPENSE
    assert payload.granularity is ForecastGranularity.MONTH

    with pytest.raises(ValueError, match="positive"):
        _point(step=0)
    with pytest.raises(ValueError, match="finite"):
        ForecastPointWrite(
            step=1,
            period_start=date(2026, 10, 1),
            expected_value=Decimal("NaN"),
            lower_80=Decimal("0"),
            upper_80=Decimal("1"),
            lower_95=Decimal("0"),
            upper_95=Decimal("1"),
        )
    with pytest.raises(ValueError, match="nested"):
        ForecastPointWrite(
            step=1,
            period_start=date(2026, 10, 1),
            expected_value=Decimal("100"),
            lower_80=Decimal("110"),
            upper_80=Decimal("120"),
            lower_95=Decimal("90"),
            upper_95=Decimal("130"),
        )


def test_forecast_run_rejects_incomplete_or_ambiguous_provenance() -> None:
    payload = _payload()
    values = dict(payload.__dict__) if hasattr(payload, "__dict__") else {
        field: getattr(payload, field) for field in payload.__dataclass_fields__
    }
    for field, invalid, message in (
        ("points", (), "at least one"),
        ("selection_metric", "rmse", "selection metric"),
        ("uncertainty_reliability", "certain", "reliability"),
        ("model_code", " ", "cannot be blank"),
        ("validation_mae", Decimal("-1"), "cannot be negative"),
        ("test_bias", Decimal("NaN"), "must be finite"),
    ):
        changed = {**values, field: invalid}
        with pytest.raises(ValueError, match=message):
            ForecastRunWrite(**changed)

    with pytest.raises(ValueError, match="contiguous"):
        ForecastRunWrite(**{**values, "points": (_point(), _point(step=3))})
    with pytest.raises(ValueError, match="unique and ordered"):
        ForecastRunWrite(
            **{
                **values,
                "points": (
                    _point(step=1, period=date(2026, 11, 1)),
                    _point(step=2, period=date(2026, 10, 1)),
                ),
            }
        )
    with pytest.raises(ValueError, match="raw personal data"):
        ForecastRunWrite(
            **{**values, "candidate_evidence": {"email": "private@example.com"}}
        )
    with pytest.raises(ValueError, match="JSON serializable"):
        ForecastRunWrite(
            **{**values, "model_parameters": {"order": object()}}
        )
    with pytest.raises(ValueError, match="declared horizon"):
        ForecastRunWrite(
            **{**values, "forecast_end": date(2026, 10, 2)}
        )


def test_repository_creates_run_and_points_under_trusted_owner() -> None:
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    run = asyncio.run(
        ForecastPersistenceRepository().create(
            session,
            user_id=user_id,
            payload=_payload(),
        )
    )
    assert run.user_id == user_id
    assert run.currency == "INR"
    assert run.horizon == 1
    assert len(run.points) == 1
    assert run.points[0].user_id == user_id
    assert run.points[0].forecast_run_id == run.id
    assert session.flush.await_count == 1


def test_repository_reads_are_owner_scoped_and_bounded() -> None:
    repository = ForecastPersistenceRepository()
    user_id, run_id = uuid4(), uuid4()
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    assert asyncio.run(
        repository.get(session, user_id=user_id, run_id=run_id)
    ) is None
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "forecast_runs.user_id =" in str(compiled)
    assert "forecast_runs.id =" in str(compiled)
    assert user_id in compiled.params.values()
    assert run_id in compiled.params.values()

    scalars = Mock()
    scalars.all.return_value = []
    session.scalars.return_value = scalars
    assert asyncio.run(
        repository.list_recent(session, user_id=user_id, limit=10)
    ) == ()
    list_statement = session.scalars.await_args.args[0]
    list_compiled = list_statement.compile(dialect=postgresql.dialect())
    assert "forecast_runs.user_id =" in str(list_compiled)
    assert "ORDER BY forecast_runs.created_at DESC" in str(list_compiled)
    assert user_id in list_compiled.params.values()
    assert 10 in list_compiled.params.values()

    for invalid in (0, 101, True):
        with pytest.raises(ValueError, match="between 1 and 100"):
            asyncio.run(
                repository.list_recent(session, user_id=user_id, limit=invalid)
            )
