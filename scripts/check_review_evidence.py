"""Fail CI on missing/misleading review evidence; targets remain reported honestly."""

import argparse
import json
from pathlib import Path


def check(reports):
    def read(name):
        return json.loads((reports / (name + ".json")).read_text(encoding="utf-8"))

    classification = read("classification_evaluation")
    integration = read("fastapi_integration")
    forecast = read("forecast_evaluation")
    assistant = read("assistant_evaluation")
    planning = read("planning_evaluation")
    performance = read("performance_evaluation")
    assert classification["selection_partition"] == "calibration_validation"
    assert classification["dataset_source_kind"] == "synthetic"
    assert not classification["production_eligible"]
    assert [
        classification[k]
        for k in ("train_records", "calibration_records", "test_records")
    ] == [12240, 4080, 4080]
    selected = next(
        x
        for x in classification["evaluations"]
        if x["candidate"] == classification["selected_candidate"]
    )
    assert all(
        0 <= selected[k] <= 1
        for k in ("accuracy", "macro_f1", "weighted_f1", "expected_calibration_error")
    )
    assert (
        integration["application_factory_wiring_verified"]
        and integration["synthetic_automatic_assignment_blocked"]
    )
    assert forecast["histories"] == 150 and forecast["series"] == 300
    assert forecast["aggregate_test"]["observation_count"] == 900
    assert not forecast["real_world_accuracy_verified"]
    assert assistant["cases"] == assistant["guardrail_passed"] == 720
    assert not assistant["live_llm_evaluated"]
    assert planning["cases"] == planning["passed"] == 1000
    assert performance["records"] == 100000 and performance["records_per_second"] > 0
    return {
        "evidence_contracts_passed": True,
        "classification_90_percent_target_met": selected["accuracy"] >= 0.9
        and selected["macro_f1"] >= 0.9,
        "real_world_validation_complete": False,
        "production_release_approved": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports", type=Path, default=Path("ml/reports/review_2026_3")
    )
    args = parser.parse_args()
    print(json.dumps(check(args.reports), indent=2))
