"""Checkpoint 11.6 owner-scoped uncertainty calibration tests."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from falcon_api.scenario_simulation import (
    INTERVAL_QUANTILE_SAMPLING_METHOD,
    PROTECTED_POINT_MASS_METHOD,
    OneTimeExpenseAssumption,
    ScenarioAssumptions,
    ScenarioCalibrationReliability,
    ScenarioCalibrationStatus,
    ScenarioReasonCode,
    build_deterministic_scenario_paths,
    calibrate_scenario_uncertainty,
)
from scenario_test_data import transient_scenario_snapshot


def _expense_case(amount: str = "25") -> ScenarioAssumptions:
    return ScenarioAssumptions(
        name="Unexpected expense",
        one_time_expenses=(
            OneTimeExpenseAssumption(
                period_start=date(2026, 10, 1),
                amount=Decimal(amount),
            ),
        ),
    )


def test_calibration_reuses_only_validation_calibrated_phase_9_bands() -> None:
    snapshot = transient_scenario_snapshot((_expense_case(),))

    calibrations = calibrate_scenario_uncertainty(snapshot)

    assert len(calibrations) == 4
    assert len({item.calibration_id for item in calibrations}) == 4
    protected = calibrations[0]
    assert protected.status is ScenarioCalibrationStatus.ELIGIBLE
    assert protected.reliability is ScenarioCalibrationReliability.NORMAL
    assert protected.sampling_method == INTERVAL_QUANTILE_SAMPLING_METHOD
    assert protected.calibration_residual_count == 12
    assert protected.points[0].raw_lower_95 == Decimal("50.0000")
    assert protected.points[0].raw_lower_80 == Decimal("60.0000")
    assert protected.points[0].raw_expected == Decimal("75.0000")
    assert protected.points[0].raw_upper_80 == Decimal("90.0000")
    assert protected.points[0].raw_upper_95 == Decimal("100.0000")
    user = calibrations[3]
    assert user.points[0].raw_lower_95 == Decimal("25.0000")
    assert user.points[0].raw_lower_80 == Decimal("35.0000")
    assert user.points[0].raw_expected == Decimal("50.0000")
    assert user.points[0].raw_upper_80 == Decimal("65.0000")
    assert user.points[0].raw_upper_95 == Decimal("75.0000")
    assert ScenarioReasonCode.VALIDATION_CALIBRATED_BANDS in user.reason_codes


def test_provisional_evidence_retains_distribution_and_reliability_label() -> None:
    snapshot = transient_scenario_snapshot((_expense_case(),))
    assert snapshot.forecast is not None
    snapshot = replace(
        snapshot,
        forecast=replace(
            snapshot.forecast,
            uncertainty_reliability="provisional",
            calibration_residual_count=2,
        ),
    )

    calibration = calibrate_scenario_uncertainty(snapshot)[0]

    assert calibration.status is ScenarioCalibrationStatus.ELIGIBLE
    assert calibration.reliability is ScenarioCalibrationReliability.PROVISIONAL
    assert ScenarioReasonCode.PROVISIONAL_CALIBRATION in calibration.reason_codes


@pytest.mark.parametrize(
    "changes",
    [
        {"calibration_residual_count": 0},
        {"uncertainty_method": "unsupported"},
        {"uncertainty_policy_version": "legacy"},
    ],
)
def test_missing_or_unsupported_calibration_falls_back_conservatively(changes) -> None:
    snapshot = transient_scenario_snapshot((_expense_case(),))
    assert snapshot.forecast is not None
    snapshot = replace(
        snapshot,
        forecast=replace(snapshot.forecast, **changes),
    )

    calibrations = calibrate_scenario_uncertainty(snapshot)

    expected_reference = calibrations[1]
    assert (
        expected_reference.status
        is ScenarioCalibrationStatus.CONSERVATIVE_FALLBACK
    )
    assert (
        expected_reference.reliability
        is ScenarioCalibrationReliability.CONSERVATIVE
    )
    assert expected_reference.sampling_method == PROTECTED_POINT_MASS_METHOD
    assert expected_reference.points[0].raw_expected == Decimal("50.0000")
    assert len({
        expected_reference.points[0].raw_lower_95,
        expected_reference.points[0].raw_lower_80,
        expected_reference.points[0].raw_expected,
        expected_reference.points[0].raw_upper_80,
        expected_reference.points[0].raw_upper_95,
    }) == 1
    assert (
        ScenarioReasonCode.CONSERVATIVE_PROTECTED_FALLBACK
        in expected_reference.reason_codes
    )


def test_missing_savings_forecast_falls_back_only_for_available_paths() -> None:
    snapshot = transient_scenario_snapshot((_expense_case(),))
    snapshot = replace(snapshot, forecast=None)

    protected, expected, upside, user = calibrate_scenario_uncertainty(snapshot)

    assert protected.status is ScenarioCalibrationStatus.CONSERVATIVE_FALLBACK
    assert expected.status is ScenarioCalibrationStatus.UNAVAILABLE
    assert upside.status is ScenarioCalibrationStatus.UNAVAILABLE
    assert user.status is ScenarioCalibrationStatus.CONSERVATIVE_FALLBACK
    assert ScenarioReasonCode.PATH_UNAVAILABLE in expected.reason_codes


def test_calibration_rejects_paths_from_another_snapshot() -> None:
    snapshot = transient_scenario_snapshot((_expense_case(),))
    paths = build_deterministic_scenario_paths(snapshot)
    mismatched = (replace(paths[0], snapshot_id="other"), *paths[1:])

    with pytest.raises(ValueError, match="same snapshot"):
        calibrate_scenario_uncertainty(snapshot, paths=mismatched)
