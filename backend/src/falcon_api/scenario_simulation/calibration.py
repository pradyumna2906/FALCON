"""Owner-scoped uncertainty calibration for Phase 11 stochastic scenarios."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID

from falcon_api.analytics.types import money
from falcon_api.forecasting.uncertainty import (
    FORECAST_UNCERTAINTY_POLICY_VERSION,
    MIN_NORMAL_CALIBRATION_RESIDUALS,
)
from falcon_api.scenario_simulation.paths import (
    DeterministicScenarioPath,
    build_deterministic_scenario_paths,
)
from falcon_api.scenario_simulation.semantics import (
    SCENARIO_UNCERTAINTY_POLICY_VERSION,
    ScenarioCalibrationReliability,
    ScenarioCalibrationStatus,
    ScenarioPathStatus,
    ScenarioReasonCode,
)
from falcon_api.scenario_simulation.snapshot import ScenarioEvidenceSnapshot


INTERVAL_QUANTILE_SAMPLING_METHOD = "phase_9_piecewise_quantile_interpolation"
PROTECTED_POINT_MASS_METHOD = "deterministic_protected_point_mass"
SUPPORTED_UNCERTAINTY_METHOD = "absolute_residual_conformal"


@dataclass(frozen=True, slots=True)
class ScenarioUncertaintyPoint:
    """Bounded inverse-CDF knots for one monthly stochastic capacity value."""

    period_start: date
    raw_lower_95: Decimal
    raw_lower_80: Decimal
    raw_expected: Decimal
    raw_upper_80: Decimal
    raw_upper_95: Decimal


@dataclass(frozen=True, slots=True)
class ScenarioUncertaintyCalibration:
    """Immutable eligibility and distribution contract for one scenario path."""

    calibration_id: str
    snapshot_id: str
    path_id: str
    policy_version: str
    status: ScenarioCalibrationStatus
    reliability: ScenarioCalibrationReliability
    sampling_method: str
    calibration_residual_count: int
    points: tuple[ScenarioUncertaintyPoint, ...]
    reason_codes: tuple[ScenarioReasonCode, ...]


def calibrate_scenario_uncertainty(
    snapshot: ScenarioEvidenceSnapshot,
    *,
    paths: tuple[DeterministicScenarioPath, ...] | None = None,
) -> tuple[ScenarioUncertaintyCalibration, ...]:
    """Convert trusted Phase 9 bands into bounded replayable distributions."""
    resolved_paths = paths or build_deterministic_scenario_paths(snapshot)
    if any(path.snapshot_id != snapshot.snapshot_id for path in resolved_paths):
        raise ValueError("Scenario calibrations require paths from the same snapshot.")
    calibrations = tuple(
        _calibrate_path(snapshot=snapshot, path=path)
        for path in resolved_paths
    )
    if len({item.calibration_id for item in calibrations}) != len(calibrations):
        raise ValueError("Scenario calibration identifiers must be unique.")
    return calibrations


def _calibrate_path(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
) -> ScenarioUncertaintyCalibration:
    forecast = snapshot.forecast
    residual_count = (
        forecast.calibration_residual_count if forecast is not None else 0
    )
    if path.status is ScenarioPathStatus.UNAVAILABLE:
        return _calibration(
            snapshot=snapshot,
            path=path,
            status=ScenarioCalibrationStatus.UNAVAILABLE,
            reliability=ScenarioCalibrationReliability.UNAVAILABLE,
            method=PROTECTED_POINT_MASS_METHOD,
            residual_count=residual_count,
            points=(),
            reasons=(*path.reason_codes, ScenarioReasonCode.PATH_UNAVAILABLE),
        )

    supported = (
        forecast is not None
        and forecast.uncertainty_method == SUPPORTED_UNCERTAINTY_METHOD
        and forecast.uncertainty_policy_version
        == FORECAST_UNCERTAINTY_POLICY_VERSION
        and residual_count > 0
    )
    if not supported:
        reasons = [*path.reason_codes]
        if forecast is not None and residual_count <= 0:
            reasons.append(ScenarioReasonCode.CALIBRATION_EVIDENCE_MISSING)
        if forecast is not None and (
            forecast.uncertainty_method != SUPPORTED_UNCERTAINTY_METHOD
            or forecast.uncertainty_policy_version
            != FORECAST_UNCERTAINTY_POLICY_VERSION
        ):
            reasons.append(ScenarioReasonCode.UNSUPPORTED_UNCERTAINTY_METHOD)
        reasons.append(ScenarioReasonCode.CONSERVATIVE_PROTECTED_FALLBACK)
        points = tuple(
            _point_mass(
                period_start=period.period_start,
                value=max(Decimal("0"), period.raw_protected_amount),
            )
            for period in path.periods
        )
        return _calibration(
            snapshot=snapshot,
            path=path,
            status=ScenarioCalibrationStatus.CONSERVATIVE_FALLBACK,
            reliability=ScenarioCalibrationReliability.CONSERVATIVE,
            method=PROTECTED_POINT_MASS_METHOD,
            residual_count=residual_count,
            points=points,
            reasons=tuple(reasons),
        )

    assert forecast is not None
    source = {item.period_start: item for item in forecast.points}
    points = tuple(
        _interval_point(
            period=period,
            source=source[period.period_start],
        )
        for period in path.periods
    )
    normal = (
        forecast.uncertainty_reliability == "normal"
        and residual_count >= MIN_NORMAL_CALIBRATION_RESIDUALS
    )
    reliability = (
        ScenarioCalibrationReliability.NORMAL
        if normal
        else ScenarioCalibrationReliability.PROVISIONAL
    )
    reasons = [
        *path.reason_codes,
        ScenarioReasonCode.VALIDATION_CALIBRATED_BANDS,
    ]
    if not normal:
        reasons.append(ScenarioReasonCode.PROVISIONAL_CALIBRATION)
    return _calibration(
        snapshot=snapshot,
        path=path,
        status=ScenarioCalibrationStatus.ELIGIBLE,
        reliability=reliability,
        method=INTERVAL_QUANTILE_SAMPLING_METHOD,
        residual_count=residual_count,
        points=points,
        reasons=tuple(reasons),
    )


def _interval_point(*, period: Any, source: Any) -> ScenarioUncertaintyPoint:
    delta = money(period.raw_expected_amount - source.expected_value)
    lower_95 = money(period.raw_protected_amount)
    expected = money(period.raw_expected_amount)
    upper_95 = money(period.raw_upside_amount)
    lower_80 = money(source.lower_80 + delta)
    upper_80 = money(source.upper_80 + delta)
    lower_80 = min(expected, max(lower_95, lower_80))
    upper_80 = max(expected, min(upper_95, upper_80))
    values = (lower_95, lower_80, expected, upper_80, upper_95)
    if any(not value.is_finite() for value in values):
        raise ValueError("Scenario uncertainty knots must be finite.")
    if values != tuple(sorted(values)):
        raise ValueError("Scenario uncertainty knots must remain ordered.")
    return ScenarioUncertaintyPoint(
        period_start=period.period_start,
        raw_lower_95=lower_95,
        raw_lower_80=lower_80,
        raw_expected=expected,
        raw_upper_80=upper_80,
        raw_upper_95=upper_95,
    )


def _point_mass(*, period_start: date, value: Decimal) -> ScenarioUncertaintyPoint:
    resolved = money(value)
    return ScenarioUncertaintyPoint(
        period_start=period_start,
        raw_lower_95=resolved,
        raw_lower_80=resolved,
        raw_expected=resolved,
        raw_upper_80=resolved,
        raw_upper_95=resolved,
    )


def _calibration(
    *,
    snapshot: ScenarioEvidenceSnapshot,
    path: DeterministicScenarioPath,
    status: ScenarioCalibrationStatus,
    reliability: ScenarioCalibrationReliability,
    method: str,
    residual_count: int,
    points: tuple[ScenarioUncertaintyPoint, ...],
    reasons: tuple[ScenarioReasonCode, ...],
) -> ScenarioUncertaintyCalibration:
    deduplicated = tuple(dict.fromkeys(reasons))
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "path_id": path.path_id,
        "policy_version": SCENARIO_UNCERTAINTY_POLICY_VERSION,
        "status": status,
        "reliability": reliability,
        "method": method,
        "residual_count": residual_count,
        "points": points,
        "reasons": deduplicated,
    }
    return ScenarioUncertaintyCalibration(
        calibration_id=_hash(payload),
        snapshot_id=snapshot.snapshot_id,
        path_id=path.path_id,
        policy_version=SCENARIO_UNCERTAINTY_POLICY_VERSION,
        status=status,
        reliability=reliability,
        sampling_method=method,
        calibration_residual_count=residual_count,
        points=points,
        reason_codes=deduplicated,
    )


def _hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported scenario calibration value: {type(value).__name__}")
