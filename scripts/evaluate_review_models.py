"""Reproduce review evidence using actual FALCON adapters; no paid services."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import asyncio
import hashlib
import json
import platform
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from threadpoolctl import threadpool_limits

from scripts.build_review_datasets import SEED, VERSION
from falcon_api.classification.artifacts import (
    ModelArtifactRegistry,
    package_model_comparison_result,
)
from falcon_api.classification.dataset import DatasetRecord, load_classification_dataset
from falcon_api.classification.training import (
    DatasetSplit,
    _candidate_estimators,
    compare_classification_models,
)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, default=str, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def load_inputs(root):
    manifest = json.loads((root / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        payload = (root / name).read_bytes()
        if (
            hashlib.sha256(payload).hexdigest() != expected["sha256"]
            or len(payload.splitlines()) != expected["records"]
        ):
            raise ValueError(f"Dataset integrity failed: {name}")
    dataset = load_classification_dataset(
        (root / "classification.jsonl").read_text(),
        json.loads((root / "classification_manifest.json").read_text()),
    )
    split = DatasetSplit(
        **{
            name: tuple(
                DatasetRecord.from_dict(row)
                for row in read_rows(root / f"classification_{name}.jsonl")
            )
            for name in ("train", "calibration", "test")
        },
        split_id=manifest["classification_split_id"],
        random_seed=SEED,
    )
    merchants = [
        {r.normalized_merchant for r in getattr(split, name)}
        for name in ("train", "calibration", "test")
    ]
    if any(a & b for i, a in enumerate(merchants) for b in merchants[i + 1 :]):
        raise ValueError("Merchant leakage across partitions")
    return dataset, split


def classification(root, reports, registry):
    dataset, split = load_inputs(root)
    curves = []
    # Learning curves consume validation only. Final test remains untouched.
    for groups_per_label in (3, 8, 15):
        selected = []
        for leaf in sorted({r.target for r in split.train}):
            groups = sorted({r.group_id for r in split.train if r.target == leaf})[
                :groups_per_label
            ]
            selected.extend(
                r for r in split.train if r.target == leaf and r.group_id in groups
            )
        for name, model in _candidate_estimators(SEED):
            started = time.perf_counter()
            model.fit([r.model_text() for r in selected], [r.target for r in selected])
            predicted = model.predict([r.model_text() for r in split.calibration])
            curves.append(
                {
                    "candidate": name.value,
                    "training_records": len(selected),
                    "validation_records": len(split.calibration),
                    "validation_accuracy": float(
                        accuracy_score([r.target for r in split.calibration], predicted)
                    ),
                    "validation_macro_f1": float(
                        f1_score(
                            [r.target for r in split.calibration],
                            predicted,
                            average="macro",
                            zero_division=0,
                        )
                    ),
                    "fit_and_validation_seconds": time.perf_counter() - started,
                }
            )
        print(f"Learning curve: {len(selected)} training records", flush=True)
    save(
        reports / "classification_learning_curves.json",
        {"selection_partition": "validation_only", "points": curves},
    )
    result = compare_classification_models(dataset, random_seed=SEED, split=split)
    save(reports / "classification_evaluation.json", result.report.to_dict())
    manifest = package_model_comparison_result(
        result, registry_root=registry, model_version="classification_2026_3_review.1"
    )
    classifier = ModelArtifactRegistry(registry).load_classifier(manifest.model_version)
    smoke = classifier.predict(split.test[0].to_features())
    chosen = next(
        e
        for e in result.report.evaluations
        if e.candidate == result.report.selected_candidate
    )
    save(
        reports / "classification_integration.json",
        {
            "model_version": smoke.model_version,
            "registry_load_verified": True,
            "feature_schema": classifier.metadata.feature_schema_version,
            "taxonomy": classifier.metadata.taxonomy_version,
            "classes": len(classifier.metadata.classes),
            "artifact_sha256": manifest.artifact_sha256,
            "production_eligible": manifest.production_eligible,
            "automatic_use_of_synthetic_model": False,
            "accuracy_target": 0.9,
            "macro_f1_target": 0.9,
            "target_met_on_synthetic_test": chosen.accuracy >= 0.9
            and chosen.macro_f1 >= 0.9,
            "real_world_accuracy_verified": False,
        },
    )
    print(
        f"Classification selected {chosen.candidate}: accuracy={chosen.accuracy:.4f}, macro-F1={chosen.macro_f1:.4f}",
        flush=True,
    )


def forecasting(root, reports):
    from falcon_api.forecasting.application import forecasting_candidates
    from falcon_api.forecasting.baselines import baseline_candidates
    from falcon_api.forecasting.evaluation import (
        RollingOriginConfig,
        build_chronological_evaluation_plan,
        calculate_forecast_error_metrics,
    )
    from falcon_api.forecasting.selection import select_forecast_model
    from falcon_api.forecasting.semantics import ForecastGranularity
    from falcon_api.forecasting.uncertainty import (
        calibrate_forecast_uncertainty,
        build_forecast_uncertainty,
    )

    rows = []
    all_actual, all_predicted, all_baseline = [], [], []
    coverage = Counter()
    started = time.perf_counter()
    for history in read_rows(root / "forecast_histories.jsonl"):
        for metric in ("income", "expense"):
            values = []
            for period in history["periods"]:
                # Causal carry-forward for unobserved training months. The original
                # missing mask remains in the fixture and report; no time compression.
                raw = period[metric]
                values.append(
                    Decimal(raw)
                    if raw is not None
                    else (values[-1] if values else Decimal(0))
                )
            values = tuple(values)
            plan = build_chronological_evaluation_plan(
                series_length=len(values),
                config=RollingOriginConfig(
                    minimum_training_points=27,
                    validation_horizon=1,
                    test_size=3,
                    maximum_folds=4,
                ),
            )
            selection = select_forecast_model(
                values=values,
                plan=plan,
                candidates=forecasting_candidates(ForecastGranularity.MONTH),
            )
            best_baseline = next(
                c
                for c in baseline_candidates(ForecastGranularity.MONTH)
                if c.code == selection.best_baseline_model_code
            )
            baseline_prediction = best_baseline.predict(values[: plan.test_start], 3)
            selected_eval = next(
                e
                for e in selection.candidate_evaluations
                if e.model_code == selection.selected_model_code
            )
            calibration = calibrate_forecast_uncertainty(evaluation=selected_eval)
            bands = build_forecast_uncertainty(
                expected=selection.final_test.predicted,
                calibration=calibration,
                floor_at_zero=True,
            )
            for actual, point in zip(selection.final_test.actual, bands, strict=True):
                for band in point.bands:
                    coverage[str(band.confidence_level)] += int(
                        band.lower <= actual <= band.upper
                    )
            all_actual.extend(selection.final_test.actual)
            all_predicted.extend(selection.final_test.predicted)
            all_baseline.extend(baseline_prediction)
            rows.append(
                {
                    "history_id": history["history_id"],
                    "regime": history["regime"],
                    "metric": metric,
                    "missing_training_months": sum(
                        p["missing"] for p in history["periods"][: plan.test_start]
                    ),
                    "selected_model": selection.selected_model_code,
                    "validation": {
                        e.model_code: asdict(e.metrics)
                        for e in selection.candidate_evaluations
                    },
                    "candidate_failures": [
                        asdict(f) for f in selection.candidate_failures
                    ],
                    "test": asdict(selection.final_test),
                    "baseline_test": asdict(
                        calculate_forecast_error_metrics(
                            actual=selection.final_test.actual,
                            predicted=baseline_prediction,
                        )
                    ),
                }
            )
        if len(rows) % 20 == 0:
            save(
                reports / "forecast_checkpoint.json",
                {"completed_series": len(rows), "results": rows},
            )
            print(f"Forecast evaluation: {len(rows)}/300 series", flush=True)
    observed = calculate_forecast_error_metrics(
        actual=tuple(all_actual), predicted=tuple(all_predicted)
    )
    baseline = calculate_forecast_error_metrics(
        actual=tuple(all_actual), predicted=tuple(all_baseline)
    )
    save(
        reports / "forecast_evaluation.json",
        {
            "source_kind": "synthetic",
            "real_world_accuracy_verified": False,
            "histories": len(rows) // 2,
            "series": len(rows),
            "months_per_history": 36,
            "final_test_months": 3,
            "validation_folds": 4,
            "missing_policy": "causal carry-forward training only; final test observed for all generated cases",
            "aggregate_test": asdict(observed),
            "aggregate_baseline_test": asdict(baseline),
            "mae_relative_improvement": str(
                (baseline.mae - observed.mae) / baseline.mae
            )
            if baseline.mae
            else None,
            "interval_calibration_residuals_per_series": 4,
            "interval_reliability": "provisional",
            "prediction_interval_coverage": {
                level: count / len(all_actual) for level, count in coverage.items()
            },
            "selected_models": dict(Counter(r["selected_model"] for r in rows)),
            "candidate_failures": dict(
                Counter(
                    f["reason"].value for r in rows for f in r["candidate_failures"]
                )
            ),
            "elapsed_seconds": time.perf_counter() - started,
            "results": rows,
        },
    )
    (reports / "forecast_checkpoint.json").unlink(missing_ok=True)


def planning(root, reports):
    from falcon_api.goal_planning.optimizer import SciPyHighsSolver, LinearSolverStatus
    from falcon_api.analytics.types import AnalyticsSummaryAggregate

    checks, failed = 0, []
    durations = []
    for row in read_rows(root / "planning_cases.jsonl"):
        income, expense = Decimal(row["income"]), Decimal(row["expenses"])
        summary = AnalyticsSummaryAggregate(
            income, expense, Decimal(0), Decimal(0), 2, 2, 0, 0, 0, 0, 0, 0, None, None
        )
        cap = max(Decimal(0), income - expense)
        bound = min(
            Decimal(row["requested_monthly_allocation"]), Decimal(row["goal_target"])
        )
        started = time.perf_counter()
        result = SciPyHighsSolver().solve(
            objective=(-1.0,),
            upper_bound_matrix=((1.0,),),
            upper_bounds=(float(cap),),
            bounds=((0.0, float(bound)),),
        )
        durations.append((time.perf_counter() - started) * 1000)
        ok = (
            summary.net_cash_flow == Decimal(row["expected"]["net_cash_flow"])
            and result.status == LinearSolverStatus.OPTIMAL
            and abs(result.values[0] - float(min(cap, bound))) < 0.0001
        )
        checks += 1
        if not ok:
            failed.append(row["case_id"])
    save(
        reports / "planning_evaluation.json",
        {
            "cases": checks,
            "passed": checks - len(failed),
            "failed_ids": failed,
            "scope": "exact live summary properties and real HiGHS adapter; full multi-goal integration separately tested by backend suites",
            "independent_oracle": "single-variable bounded allocation optimum=min(capacity,requested,target)",
            "solver_p95_ms": float(np.percentile(durations, 95)),
        },
    )


async def assistant(root, reports):
    from falcon_api.assistant import (
        AssistantEvidenceRecord,
        AssistantEvidenceSource,
        AssistantReliability,
        AssistantIntent,
        build_evidence_packet,
        GroundedAssistantGenerator,
        AssistantModelOutput,
        AssistantGeneratedClaim,
        AssistantClaimKind,
        AssistantModelResult,
        AssistantModelUsage,
    )
    from falcon_api.assistant.model import AssistantModelUnavailableError
    from falcon_api.assistant.verification import AssistantVerificationError

    now = datetime(2026, 10, 4, 6, tzinfo=UTC)
    outcomes = []

    class ReplayModel:
        def __init__(self, row):
            self.row = row

        async def generate(self, packet):
            topic = self.row["topic"]
            if topic == "provider_failure":
                raise AssistantModelUnavailableError("Synthetic provider outage")
            net = self.row["expected_facts"]["net_cash_flow"]
            text = f"Your recorded net cash flow is INR {net}."
            kind = AssistantClaimKind.OBSERVATION
            if topic == "numeric_hallucination":
                text = "Your net cash flow is INR 999999."
            if topic == "evidence_mismatch":
                kind = AssistantClaimKind.FORECAST
            return AssistantModelResult(
                output=AssistantModelOutput(
                    claims=(
                        AssistantGeneratedClaim(
                            kind=kind,
                            text=text,
                            evidence_ids=(packet.evidence[0].evidence_id,),
                        ),
                    )
                ),
                usage=AssistantModelUsage(100, 30, 1),
                provider_id="offline_replay",
                model_id="synthetic_fixture",
            )

    for row in read_rows(root / "assistant_cases.jsonl"):
        topic = row["topic"]
        record = AssistantEvidenceRecord(
            source=AssistantEvidenceSource.ANALYTICS,
            reference=row["case_id"],
            label="Recorded financial summary",
            cutoff_at=now,
            policy_version="2026.1",
            reliability=AssistantReliability.NORMAL,
            payload={
                "currency": "INR",
                "cash_flow": {
                    "gross_income": Decimal(row["context"]["income"]),
                    "total_expense": Decimal(row["context"]["expenses"]),
                    "net_cash_flow": Decimal(row["expected_facts"]["net_cash_flow"]),
                },
            },
        )
        question = row["messages"][-1]["content"]
        packet = build_evidence_packet(
            question=question,
            intent=AssistantIntent.EXPLAIN_DASHBOARD,
            user_id=UUID(int=1),
            requested_sources=(AssistantEvidenceSource.ANALYTICS,),
            evidence=() if topic == "missing_data" else (record,),
            created_at=now,
        )
        started = time.perf_counter()
        try:
            result = await GroundedAssistantGenerator(ReplayModel(row)).generate(packet)
        except AssistantModelUnavailableError:
            if topic != "provider_failure":
                raise
            outcomes.append(
                {
                    "case_id": row["case_id"],
                    "topic": topic,
                    "status": "provider_error_propagated",
                    "refusal_reason": None,
                    "guardrail_expectation_passed": True,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
            continue
        except AssistantVerificationError as error:
            outcomes.append(
                {
                    "case_id": row["case_id"],
                    "topic": topic,
                    "status": "verification_blocked",
                    "refusal_reason": str(error),
                    "guardrail_expectation_passed": topic
                    in ("numeric_hallucination", "evidence_mismatch"),
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
            continue
        # These are guardrail expectations, not claimed natural-language quality.
        positive = topic in ("cash_flow", "budget", "forecast", "goal", "follow_up")
        acceptable = result.answer.status.value in (
            ("answered", "limited") if positive else ("refused", "unavailable")
        )
        outcomes.append(
            {
                "case_id": row["case_id"],
                "topic": topic,
                "status": result.answer.status.value,
                "refusal_reason": str(result.answer.refusal_reason),
                "guardrail_expectation_passed": acceptable,
                "latency_ms": (time.perf_counter() - started) * 1000,
            }
        )
    save(
        reports / "assistant_evaluation.json",
        {
            "cases": len(outcomes),
            "mode": "offline deterministic provider replay",
            "live_llm_evaluated": False,
            "provider_failure_scope": "generation boundary propagates provider exception; API safe-error behavior tested separately",
            "conversation_history_integration": "separate backend and browser tests; fixture follow-up text alone does not prove history retrieval",
            "task_completion_or_live_answer_accuracy": None,
            "limitations": "Forecast/goal cases exercise an observation replay; live task-specific responses still require provider review",
            "guardrail_passed": sum(
                x["guardrail_expectation_passed"] for x in outcomes
            ),
            "failures": [x for x in outcomes if not x["guardrail_expectation_passed"]],
            "p95_ms": float(np.percentile([x["latency_ms"] for x in outcomes], 95)),
            "outcomes": outcomes,
        },
    )


def performance(root, reports):
    import tracemalloc
    from falcon_api.classification.features import (
        TransactionFeatureInput,
        build_classification_features,
    )
    from falcon_api.models.enums import TransactionType
    from datetime import date

    started = time.perf_counter()
    tracemalloc.start()
    count = 0
    for row in read_rows(root / "performance_transactions.jsonl"):
        build_classification_features(
            TransactionFeatureInput(
                description=row["description"],
                merchant_name=None,
                transaction_type=TransactionType.EXPENSE,
                signed_amount=Decimal(row["amount"]),
                transaction_date=date.fromisoformat(row["date"]),
                account_currency=row["currency"],
            )
        )
        count += 1
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - started
    save(
        reports / "performance_evaluation.json",
        {
            "records": count,
            "elapsed_seconds": elapsed,
            "records_per_second": count / elapsed,
            "peak_python_bytes": peak,
            "scope": "JSONL loading and actual classification feature extraction; not HTTP import or database throughput",
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=Path("data/synthetic/review_2026_3")
    )
    parser.add_argument(
        "--reports", type=Path, default=Path("ml/reports/review_2026_3")
    )
    parser.add_argument(
        "--registry", type=Path, default=Path("ml/artifacts/classification")
    )
    parser.add_argument(
        "--section",
        choices=(
            "classification",
            "forecasting",
            "planning",
            "assistant",
            "performance",
            "all",
        ),
        default="all",
    )
    args = parser.parse_args()
    # Verify all fixture checksums even when running a single non-classification section.
    load_inputs(args.data)
    with threadpool_limits(limits=1):
        for section in (
            "classification",
            "forecasting",
            "planning",
            "assistant",
            "performance",
        ):
            if args.section in (section, "all"):
                if (args.reports / f"{section}_evaluation.json").exists():
                    parser.error(
                        f"Evidence for {section} already exists. Choose a new reports directory."
                    )
                if section == "assistant":
                    asyncio.run(assistant(args.data, args.reports))
                else:
                    globals()[section](
                        args.data, args.reports, args.registry
                    ) if section == "classification" else globals()[section](
                        args.data, args.reports
                    )


if __name__ == "__main__":
    main()
