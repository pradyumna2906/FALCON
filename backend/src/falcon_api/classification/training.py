"""Reproducible model comparison for Phase 7 transaction classification."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import platform
import time
import tracemalloc
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Iterable, Sequence

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from falcon_api.classification.dataset import (
    ClassificationDataset,
    DatasetRecord,
    DatasetSourceKind,
)
from falcon_api.classification.rules import ClassificationRulesEngine
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    subcategory_definition,
)


MODEL_EVALUATION_SCHEMA_VERSION = "2026.1"
DEFAULT_RANDOM_SEED = 730_021
ABSTAIN_LABEL = "__abstain__"


class CandidateName(StrEnum):
    """The approved first comparison set."""

    MAJORITY_BASELINE = "majority_baseline"
    KEYWORD_RULE_BASELINE = "keyword_rule_baseline"
    TFIDF_LOGISTIC_REGRESSION = "tfidf_logistic_regression"
    TFIDF_CALIBRATED_LINEAR_SVM = "tfidf_calibrated_linear_svm"


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    """Group-isolated train, calibration, and final-test records."""

    train: tuple[DatasetRecord, ...]
    calibration: tuple[DatasetRecord, ...]
    test: tuple[DatasetRecord, ...]
    split_id: str
    random_seed: int

    def __post_init__(self) -> None:
        partitions = (self.train, self.calibration, self.test)
        if any(not partition for partition in partitions):
            raise ValueError("Every dataset split partition must be non-empty.")
        group_sets = tuple(
            {record.group_id for record in partition} for partition in partitions
        )
        if any(
            left.intersection(right)
            for index, left in enumerate(group_sets)
            for right in group_sets[index + 1 :]
        ):
            raise ValueError("Dataset groups cannot cross split partitions.")


@dataclass(frozen=True, slots=True)
class ConfidenceThresholds:
    """Thresholds selected only from the calibration partition."""

    automatic_confidence: float
    suggestion_confidence: float
    minimum_top_two_margin: float
    calibration_automatic_precision: float | None
    calibration_suggestion_precision: float | None
    calibration_automatic_coverage: float
    calibration_suggestion_coverage: float


@dataclass(frozen=True, slots=True)
class LabelMetric:
    """Precision, recall, and support for one taxonomy label."""

    label: str
    precision: float
    recall: float
    support: int


@dataclass(frozen=True, slots=True)
class ConfusionEntry:
    """One non-zero, sparse confusion-matrix cell."""

    actual: str
    predicted: str
    count: int


@dataclass(frozen=True, slots=True)
class DecisionMetrics:
    """Held-out outcomes after automatic/suggested/abstained policy."""

    automatic_count: int
    suggested_count: int
    abstained_count: int
    automatic_precision: float | None
    suggestion_precision: float | None
    automatic_coverage: float
    suggestion_coverage: float
    abstention_rate: float


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Publishable evidence for one baseline or learned candidate."""

    candidate: CandidateName
    macro_f1: float
    weighted_f1: float
    top_two_accuracy: float
    expected_calibration_error: float
    prediction_coverage: float
    per_subcategory: tuple[LabelMetric, ...]
    per_category: tuple[LabelMetric, ...]
    confusion: tuple[ConfusionEntry, ...]
    unseen_merchant_macro_f1: float | None
    unseen_merchant_coverage: float
    mean_inference_ms: float
    p95_inference_ms: float
    peak_python_inference_bytes: int
    artifact_size_bytes: int
    artifact_sha256: str
    hyperparameters: dict[str, object]
    thresholds: ConfidenceThresholds | None
    decisions: DecisionMetrics | None


@dataclass(frozen=True, slots=True)
class ModelComparisonReport:
    """Complete selection record consumed by the future artifact registry."""

    evaluation_schema_version: str
    dataset_version: str
    dataset_sha256: str
    dataset_source_kind: DatasetSourceKind
    feature_schema_version: str
    taxonomy_version: str
    split_id: str
    random_seed: int
    library_versions: dict[str, str]
    train_records: int
    calibration_records: int
    test_records: int
    evaluations: tuple[CandidateEvaluation, ...]
    selected_candidate: CandidateName
    selected_thresholds: ConfidenceThresholds
    production_eligible: bool
    deferred_candidates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible evidence without an estimator object."""
        value = asdict(self)
        value["dataset_source_kind"] = self.dataset_source_kind.value
        value["selected_candidate"] = self.selected_candidate.value
        for evaluation in value["evaluations"]:
            evaluation["candidate"] = evaluation["candidate"].value
        return value

    def to_json(self) -> str:
        """Serialize evidence deterministically for review and version control."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


@dataclass(frozen=True, slots=True)
class ModelComparisonResult:
    """Evaluation report plus the in-memory selected estimator."""

    report: ModelComparisonReport
    selected_estimator: Pipeline


def group_stratified_split(
    dataset: ClassificationDataset,
    *,
    random_seed: int = DEFAULT_RANDOM_SEED,
    calibration_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> DatasetSplit:
    """Split every label by opaque group and prevent merchant leakage."""
    if type(random_seed) is not int or random_seed < 0:
        raise ValueError("random_seed must be a non-negative integer.")
    for name, fraction in (
        ("calibration_fraction", calibration_fraction),
        ("test_fraction", test_fraction),
    ):
        if not isinstance(fraction, float) or not 0 < fraction < 0.5:
            raise ValueError(f"{name} must be a float in (0, 0.5).")
    if calibration_fraction + test_fraction >= 0.8:
        raise ValueError("At least 20 percent of groups must remain for training.")

    groups: dict[str, list[DatasetRecord]] = defaultdict(list)
    for record in dataset.records:
        groups[record.group_id].append(record)
    groups_by_label: dict[str, list[str]] = defaultdict(list)
    for group_id, records in groups.items():
        labels = {record.target for record in records}
        if len(labels) != 1:
            raise ValueError("A split group cannot contain multiple labels.")
        groups_by_label[labels.pop()].append(group_id)

    assignments: dict[str, str] = {}
    for label, label_groups in sorted(groups_by_label.items()):
        if len(label_groups) < 3:
            raise ValueError(
                f"Label {label!r} requires at least three independent groups."
            )
        ordered = sorted(
            label_groups,
            key=lambda group_id: _seeded_digest(random_seed, label, group_id),
        )
        test_count = max(1, round(len(ordered) * test_fraction))
        calibration_count = max(1, round(len(ordered) * calibration_fraction))
        if test_count + calibration_count >= len(ordered):
            calibration_count = 1
            test_count = 1
        for group_id in ordered[:test_count]:
            assignments[group_id] = "test"
        for group_id in ordered[test_count : test_count + calibration_count]:
            assignments[group_id] = "calibration"
        for group_id in ordered[test_count + calibration_count :]:
            assignments[group_id] = "train"

    partitions: dict[str, list[DatasetRecord]] = defaultdict(list)
    for group_id, records in groups.items():
        partitions[assignments[group_id]].extend(records)
    for records in partitions.values():
        records.sort(key=lambda record: record.record_id)
    split_payload = {
        partition: [record.record_id for record in partitions[partition]]
        for partition in ("train", "calibration", "test")
    }
    split_id = "split_" + hashlib.sha256(
        json.dumps(split_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return DatasetSplit(
        train=tuple(partitions["train"]),
        calibration=tuple(partitions["calibration"]),
        test=tuple(partitions["test"]),
        split_id=split_id,
        random_seed=random_seed,
    )


def compare_classification_models(
    dataset: ClassificationDataset,
    *,
    random_seed: int = DEFAULT_RANDOM_SEED,
    minimum_automatic_precision: float = 0.95,
    minimum_suggestion_precision: float = 0.70,
) -> ModelComparisonResult:
    """Train approved candidates and select by held-out macro-F1."""
    _validate_precision_target(
        minimum_automatic_precision, name="minimum_automatic_precision"
    )
    _validate_precision_target(
        minimum_suggestion_precision, name="minimum_suggestion_precision"
    )
    if minimum_suggestion_precision > minimum_automatic_precision:
        raise ValueError("Suggestion precision cannot exceed automatic precision.")

    split = group_stratified_split(dataset, random_seed=random_seed)
    labels = tuple(item.label for item in dataset.manifest.label_counts)
    if len(labels) < 2:
        raise ValueError("Model comparison requires at least two taxonomy labels.")
    training_counts = Counter(_targets(split.train))
    if any(training_counts[label] < 3 for label in labels):
        raise ValueError(
            "Every label requires at least three training records for calibration."
        )
    evaluations: list[CandidateEvaluation] = []
    evaluations.append(_evaluate_majority_baseline(split, labels))
    evaluations.append(_evaluate_keyword_baseline(split, labels))

    trained: dict[CandidateName, Pipeline] = {}
    for candidate, estimator in _candidate_estimators(random_seed):
        estimator.fit(_texts(split.train), _targets(split.train))
        trained[candidate] = estimator
        calibration_probabilities = estimator.predict_proba(_texts(split.calibration))
        thresholds = select_confidence_thresholds(
            _targets(split.calibration),
            calibration_probabilities,
            tuple(estimator.classes_),
            minimum_automatic_precision=minimum_automatic_precision,
            minimum_suggestion_precision=minimum_suggestion_precision,
        )
        evaluations.append(
            _evaluate_learned_candidate(
                candidate,
                estimator,
                split,
                labels,
                thresholds,
            )
        )

    learned_evaluations = tuple(
        item
        for item in evaluations
        if item.candidate
        in {
            CandidateName.TFIDF_LOGISTIC_REGRESSION,
            CandidateName.TFIDF_CALIBRATED_LINEAR_SVM,
        }
    )
    selected = max(
        learned_evaluations,
        key=lambda item: (
            item.macro_f1,
            -item.expected_calibration_error,
            item.top_two_accuracy,
            -item.mean_inference_ms,
            -item.artifact_size_bytes,
            item.candidate.value,
        ),
    )
    if selected.thresholds is None:
        raise RuntimeError("A learned candidate must publish confidence thresholds.")
    report = ModelComparisonReport(
        evaluation_schema_version=MODEL_EVALUATION_SCHEMA_VERSION,
        dataset_version=dataset.manifest.dataset_version,
        dataset_sha256=dataset.manifest.records_sha256,
        dataset_source_kind=dataset.manifest.source_kind,
        feature_schema_version=dataset.manifest.feature_schema_version,
        taxonomy_version=dataset.manifest.taxonomy_version,
        split_id=split.split_id,
        random_seed=random_seed,
        library_versions=_library_versions(),
        train_records=len(split.train),
        calibration_records=len(split.calibration),
        test_records=len(split.test),
        evaluations=tuple(evaluations),
        selected_candidate=selected.candidate,
        selected_thresholds=selected.thresholds,
        production_eligible=_production_gate(
            dataset.manifest.source_kind,
            selected,
            minimum_automatic_precision=minimum_automatic_precision,
        ),
        deferred_candidates=(
            "Structured boosting deferred: the reference dataset does not justify "
            "additional complexity.",
            "MiniLM deferred: compact TF-IDF candidates meet the first comparison "
            "contract without transformer latency or artifact cost.",
        ),
    )
    return ModelComparisonResult(
        report=report,
        selected_estimator=trained[selected.candidate],
    )


def select_confidence_thresholds(
    y_true: Sequence[str],
    probabilities: np.ndarray,
    classes: Sequence[str],
    *,
    minimum_automatic_precision: float = 0.95,
    minimum_suggestion_precision: float = 0.70,
) -> ConfidenceThresholds:
    """Select coverage-maximizing thresholds from calibration evidence only."""
    _validate_probability_inputs(y_true, probabilities, classes)
    _validate_precision_target(
        minimum_automatic_precision, name="minimum_automatic_precision"
    )
    _validate_precision_target(
        minimum_suggestion_precision, name="minimum_suggestion_precision"
    )
    if minimum_suggestion_precision > minimum_automatic_precision:
        raise ValueError("Suggestion precision cannot exceed automatic precision.")

    top_indices = np.argmax(probabilities, axis=1)
    top_confidence = probabilities[np.arange(len(y_true)), top_indices]
    ordered = np.sort(probabilities, axis=1)
    margins = ordered[:, -1] - ordered[:, -2]
    class_array = np.asarray(classes)
    predictions = class_array[top_indices]
    truth = np.asarray(y_true)
    correct = predictions == truth
    minimum_count = max(2, math.ceil(len(y_true) * 0.05))

    automatic = _best_threshold_pair(
        top_confidence,
        margins,
        correct,
        target_precision=minimum_automatic_precision,
        minimum_count=minimum_count,
    )
    auto_confidence, minimum_margin, auto_precision, auto_coverage = automatic
    suggestion = _best_confidence_at_margin(
        top_confidence,
        margins,
        correct,
        target_precision=minimum_suggestion_precision,
        minimum_count=minimum_count,
        minimum_margin=minimum_margin,
        maximum_confidence=auto_confidence,
    )
    suggest_confidence, suggest_precision, suggest_coverage = suggestion
    return ConfidenceThresholds(
        automatic_confidence=auto_confidence,
        suggestion_confidence=suggest_confidence,
        minimum_top_two_margin=minimum_margin,
        calibration_automatic_precision=auto_precision,
        calibration_suggestion_precision=suggest_precision,
        calibration_automatic_coverage=auto_coverage,
        calibration_suggestion_coverage=suggest_coverage,
    )


def _candidate_estimators(
    random_seed: int,
) -> tuple[tuple[CandidateName, Pipeline], ...]:
    vectorizer = {
        "ngram_range": (1, 2),
        "min_df": 1,
        "max_features": 40_000,
        "sublinear_tf": True,
        "strip_accents": "unicode",
    }
    return (
        (
            CandidateName.TFIDF_LOGISTIC_REGRESSION,
            Pipeline(
                (
                    ("tfidf", TfidfVectorizer(**vectorizer)),
                    (
                        "classifier",
                        LogisticRegression(
                            C=4.0,
                            class_weight="balanced",
                            max_iter=2_000,
                            random_state=random_seed,
                            solver="lbfgs",
                        ),
                    ),
                )
            ),
        ),
        (
            CandidateName.TFIDF_CALIBRATED_LINEAR_SVM,
            Pipeline(
                (
                    ("tfidf", TfidfVectorizer(**vectorizer)),
                    (
                        "classifier",
                        CalibratedClassifierCV(
                            LinearSVC(
                                C=1.0,
                                class_weight="balanced",
                                random_state=random_seed,
                            ),
                            cv=3,
                            method="sigmoid",
                        ),
                    ),
                )
            ),
        ),
    )


def _evaluate_majority_baseline(
    split: DatasetSplit,
    labels: tuple[str, ...],
) -> CandidateEvaluation:
    counts = Counter(_targets(split.train))
    ordered = sorted(labels, key=lambda label: (-counts[label], label))
    majority = ordered[0]
    probabilities = np.asarray(
        [[counts[label] / len(split.train) for label in labels]] * len(split.test)
    )
    predictions = [majority] * len(split.test)
    return _build_evaluation(
        candidate=CandidateName.MAJORITY_BASELINE,
        split=split,
        labels=labels,
        predictions=predictions,
        probabilities=probabilities,
        probability_classes=labels,
        inference_durations_ms=(),
        peak_python_bytes=0,
        artifact_bytes=_serialized_bytes({"majority": majority, "counts": counts}),
        hyperparameters={"strategy": "most_frequent"},
        thresholds=None,
    )


def _evaluate_keyword_baseline(
    split: DatasetSplit,
    labels: tuple[str, ...],
) -> CandidateEvaluation:
    engine = ClassificationRulesEngine()
    predictions: list[str | None] = []
    confidences: list[float] = []
    durations: list[float] = []
    tracemalloc.start()
    try:
        for record in split.test:
            started = time.perf_counter_ns()
            evaluation = engine.evaluate(record.to_features())
            durations.append((time.perf_counter_ns() - started) / 1_000_000)
            selected = evaluation.selected
            predictions.append(selected.subcategory.value if selected else None)
            confidences.append(float(selected.confidence) if selected else 0.0)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return _build_evaluation(
        candidate=CandidateName.KEYWORD_RULE_BASELINE,
        split=split,
        labels=labels,
        predictions=predictions,
        probabilities=None,
        probability_classes=(),
        confidences=confidences,
        inference_durations_ms=tuple(durations),
        peak_python_bytes=peak,
        artifact_bytes=_serialized_bytes(engine),
        hyperparameters={
            "ruleset_version": engine.ruleset_version,
            "behavior": "abstain_on_no_match_or_conflict",
        },
        thresholds=None,
    )


def _evaluate_learned_candidate(
    candidate: CandidateName,
    estimator: Pipeline,
    split: DatasetSplit,
    labels: tuple[str, ...],
    thresholds: ConfidenceThresholds,
) -> CandidateEvaluation:
    durations: list[float] = []
    rows: list[np.ndarray] = []
    tracemalloc.start()
    try:
        for text in _texts(split.test):
            started = time.perf_counter_ns()
            rows.append(estimator.predict_proba([text])[0])
            durations.append((time.perf_counter_ns() - started) / 1_000_000)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    probabilities = np.asarray(rows)
    classes = tuple(estimator.classes_)
    top_indices = np.argmax(probabilities, axis=1)
    predictions = [classes[index] for index in top_indices]
    return _build_evaluation(
        candidate=candidate,
        split=split,
        labels=labels,
        predictions=predictions,
        probabilities=probabilities,
        probability_classes=classes,
        inference_durations_ms=tuple(durations),
        peak_python_bytes=peak,
        artifact_bytes=_serialized_bytes(estimator),
        hyperparameters=_json_safe(estimator.get_params(deep=True)),
        thresholds=thresholds,
    )


def _build_evaluation(
    *,
    candidate: CandidateName,
    split: DatasetSplit,
    labels: tuple[str, ...],
    predictions: Sequence[str | None],
    probabilities: np.ndarray | None,
    probability_classes: Sequence[str],
    inference_durations_ms: Sequence[float],
    peak_python_bytes: int,
    artifact_bytes: bytes,
    hyperparameters: dict[str, object],
    thresholds: ConfidenceThresholds | None,
    confidences: Sequence[float] | None = None,
) -> CandidateEvaluation:
    truth = _targets(split.test)
    safe_predictions = [prediction or ABSTAIN_LABEL for prediction in predictions]
    macro_f1 = f1_score(
        truth, safe_predictions, labels=labels, average="macro", zero_division=0
    )
    weighted_f1 = f1_score(
        truth, safe_predictions, labels=labels, average="weighted", zero_division=0
    )
    per_subcategory = _label_metrics(truth, safe_predictions, labels)
    category_truth = [_parent_category(label) for label in truth]
    category_predictions = [
        _parent_category(label) if label != ABSTAIN_LABEL else ABSTAIN_LABEL
        for label in safe_predictions
    ]
    category_labels = tuple(code.value for code in ClassificationCategoryCode)
    per_category = _label_metrics(
        category_truth, category_predictions, category_labels
    )
    coverage = sum(prediction is not None for prediction in predictions) / len(truth)
    if probabilities is not None:
        top_two = _top_two_accuracy(
            truth, probabilities, tuple(probability_classes)
        )
        confidence_values = np.max(probabilities, axis=1)
    else:
        top_two = sum(
            prediction == actual
            for prediction, actual in zip(predictions, truth, strict=True)
        ) / len(truth)
        confidence_values = np.asarray(confidences, dtype=float)
    ece = _expected_calibration_error(
        truth, predictions, confidence_values
    )
    unseen_indices = [
        index for index, record in enumerate(split.test) if record.merchant_group
    ]
    unseen_f1 = None
    unseen_coverage = 0.0
    if unseen_indices:
        unseen_truth = [truth[index] for index in unseen_indices]
        unseen_predictions = [safe_predictions[index] for index in unseen_indices]
        unseen_f1 = f1_score(
            unseen_truth,
            unseen_predictions,
            labels=labels,
            average="macro",
            zero_division=0,
        )
        unseen_coverage = sum(
            predictions[index] is not None for index in unseen_indices
        ) / len(unseen_indices)
    decision_metrics = None
    if thresholds is not None and probabilities is not None:
        decision_metrics = _decision_metrics(
            truth,
            probabilities,
            tuple(probability_classes),
            thresholds,
        )
    durations = sorted(inference_durations_ms)
    mean_latency = sum(durations) / len(durations) if durations else 0.0
    p95_latency = _percentile(durations, 0.95) if durations else 0.0
    return CandidateEvaluation(
        candidate=candidate,
        macro_f1=round(float(macro_f1), 8),
        weighted_f1=round(float(weighted_f1), 8),
        top_two_accuracy=round(float(top_two), 8),
        expected_calibration_error=round(float(ece), 8),
        prediction_coverage=round(coverage, 8),
        per_subcategory=per_subcategory,
        per_category=per_category,
        confusion=_sparse_confusion(truth, safe_predictions, labels),
        unseen_merchant_macro_f1=(
            round(float(unseen_f1), 8) if unseen_f1 is not None else None
        ),
        unseen_merchant_coverage=round(unseen_coverage, 8),
        mean_inference_ms=round(mean_latency, 6),
        p95_inference_ms=round(p95_latency, 6),
        peak_python_inference_bytes=peak_python_bytes,
        artifact_size_bytes=len(artifact_bytes),
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        hyperparameters=hyperparameters,
        thresholds=thresholds,
        decisions=decision_metrics,
    )


def _label_metrics(
    truth: Sequence[str],
    predictions: Sequence[str],
    labels: Sequence[str],
) -> tuple[LabelMetric, ...]:
    precision, recall, _, support = precision_recall_fscore_support(
        truth,
        predictions,
        labels=labels,
        zero_division=0,
    )
    return tuple(
        LabelMetric(
            label=label,
            precision=round(float(precision[index]), 8),
            recall=round(float(recall[index]), 8),
            support=int(support[index]),
        )
        for index, label in enumerate(labels)
    )


def _sparse_confusion(
    truth: Sequence[str],
    predictions: Sequence[str],
    labels: tuple[str, ...],
) -> tuple[ConfusionEntry, ...]:
    matrix_labels = labels + (ABSTAIN_LABEL,)
    matrix = confusion_matrix(truth, predictions, labels=matrix_labels)
    return tuple(
        ConfusionEntry(
            actual=actual,
            predicted=predicted,
            count=int(matrix[row, column]),
        )
        for row, actual in enumerate(matrix_labels)
        for column, predicted in enumerate(matrix_labels)
        if matrix[row, column]
    )


def _expected_calibration_error(
    truth: Sequence[str],
    predictions: Sequence[str | None],
    confidences: np.ndarray,
    *,
    bins: int = 10,
) -> float:
    if len(truth) != len(predictions) or len(truth) != len(confidences):
        raise ValueError("Calibration arrays must have equal length.")
    total = len(truth)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        if index == 0:
            mask = (confidences >= lower) & (confidences <= upper)
        else:
            mask = (confidences > lower) & (confidences <= upper)
        count = int(np.sum(mask))
        if not count:
            continue
        selected = np.flatnonzero(mask)
        accuracy = sum(
            predictions[position] == truth[position] for position in selected
        ) / count
        confidence = float(np.mean(confidences[mask]))
        error += count / total * abs(accuracy - confidence)
    return error


def _decision_metrics(
    truth: Sequence[str],
    probabilities: np.ndarray,
    classes: tuple[str, ...],
    thresholds: ConfidenceThresholds,
) -> DecisionMetrics:
    top_indices = np.argmax(probabilities, axis=1)
    ordered = np.sort(probabilities, axis=1)
    confidence = probabilities[np.arange(len(truth)), top_indices]
    margin = ordered[:, -1] - ordered[:, -2]
    predictions = np.asarray(classes)[top_indices]
    truth_array = np.asarray(truth)
    margin_mask = margin >= thresholds.minimum_top_two_margin
    automatic = margin_mask & (confidence >= thresholds.automatic_confidence)
    suggested = (
        margin_mask
        & ~automatic
        & (confidence >= thresholds.suggestion_confidence)
    )
    abstained = ~(automatic | suggested)
    auto_count = int(np.sum(automatic))
    suggest_count = int(np.sum(suggested))
    total = len(truth)
    return DecisionMetrics(
        automatic_count=auto_count,
        suggested_count=suggest_count,
        abstained_count=int(np.sum(abstained)),
        automatic_precision=(
            round(float(np.mean(predictions[automatic] == truth_array[automatic])), 8)
            if auto_count
            else None
        ),
        suggestion_precision=(
            round(float(np.mean(predictions[suggested] == truth_array[suggested])), 8)
            if suggest_count
            else None
        ),
        automatic_coverage=round(auto_count / total, 8),
        suggestion_coverage=round(suggest_count / total, 8),
        abstention_rate=round(float(np.mean(abstained)), 8),
    )


def _best_threshold_pair(
    confidence: np.ndarray,
    margins: np.ndarray,
    correct: np.ndarray,
    *,
    target_precision: float,
    minimum_count: int,
) -> tuple[float, float, float | None, float]:
    choices: list[tuple[float, float, float, int]] = []
    for margin in (0.0, 0.02, 0.05, 0.10, 0.15, 0.20):
        for threshold in (value / 100 for value in range(40, 100)):
            mask = (confidence >= threshold) & (margins >= margin)
            count = int(np.sum(mask))
            if count < minimum_count:
                continue
            precision = float(np.mean(correct[mask]))
            if precision >= target_precision:
                choices.append((threshold, margin, precision, count))
    if not choices:
        return 1.0, 1.0, None, 0.0
    threshold, margin, precision, count = max(
        choices,
        key=lambda item: (item[3], -item[0], -item[1], item[2]),
    )
    return threshold, margin, precision, count / len(confidence)


def _best_confidence_at_margin(
    confidence: np.ndarray,
    margins: np.ndarray,
    correct: np.ndarray,
    *,
    target_precision: float,
    minimum_count: int,
    minimum_margin: float,
    maximum_confidence: float,
) -> tuple[float, float | None, float]:
    choices: list[tuple[float, float, int]] = []
    for threshold in (value / 100 for value in range(20, 100)):
        if threshold > maximum_confidence:
            continue
        mask = (confidence >= threshold) & (margins >= minimum_margin)
        count = int(np.sum(mask))
        if count < minimum_count:
            continue
        precision = float(np.mean(correct[mask]))
        if precision >= target_precision:
            choices.append((threshold, precision, count))
    if not choices:
        return maximum_confidence, None, 0.0
    threshold, precision, count = max(
        choices,
        key=lambda item: (item[2], -item[0], item[1]),
    )
    return threshold, precision, count / len(confidence)


def _top_two_accuracy(
    truth: Sequence[str],
    probabilities: np.ndarray,
    classes: tuple[str, ...],
) -> float:
    class_array = np.asarray(classes)
    top_two = np.argsort(probabilities, axis=1)[:, -2:]
    return sum(
        actual in class_array[indices]
        for actual, indices in zip(truth, top_two, strict=True)
    ) / len(truth)


def _validate_probability_inputs(
    y_true: Sequence[str],
    probabilities: np.ndarray,
    classes: Sequence[str],
) -> None:
    if not y_true:
        raise ValueError("Calibration truth cannot be empty.")
    if not isinstance(probabilities, np.ndarray) or probabilities.ndim != 2:
        raise TypeError("probabilities must be a two-dimensional numpy array.")
    if probabilities.shape != (len(y_true), len(classes)):
        raise ValueError("Probability dimensions do not match truth and classes.")
    if len(classes) < 2 or len(set(classes)) != len(classes):
        raise ValueError("Calibration requires at least two unique classes.")
    if not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0):
        raise ValueError("Probabilities must be finite and non-negative.")
    if not np.allclose(np.sum(probabilities, axis=1), 1.0):
        raise ValueError("Each probability row must sum to one.")


def _validate_precision_target(value: float, *, name: str) -> None:
    if not isinstance(value, float) or not 0 < value <= 1:
        raise ValueError(f"{name} must be a float in (0, 1].")


def _texts(records: Iterable[DatasetRecord]) -> list[str]:
    return [record.model_text() for record in records]


def _targets(records: Iterable[DatasetRecord]) -> list[str]:
    return [record.target for record in records]


def _parent_category(subcategory: str) -> str:
    code = ClassificationSubcategoryCode(subcategory)
    return subcategory_definition(code)[0].value


def _seeded_digest(random_seed: int, label: str, group_id: str) -> str:
    return hashlib.sha256(
        f"{random_seed}:{label}:{group_id}".encode()
    ).hexdigest()


def _serialized_bytes(value: object) -> bytes:
    return pickle.dumps(value, protocol=5)


def _library_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }


def _production_gate(
    source_kind: DatasetSourceKind,
    selected: CandidateEvaluation,
    *,
    minimum_automatic_precision: float,
) -> bool:
    decisions = selected.decisions
    thresholds = selected.thresholds
    return bool(
        source_kind is DatasetSourceKind.REVIEWED_DEIDENTIFIED
        and selected.macro_f1 >= 0.70
        and decisions is not None
        and decisions.automatic_precision is not None
        and decisions.automatic_precision >= minimum_automatic_precision
        and thresholds is not None
        and thresholds.calibration_automatic_precision is not None
        and thresholds.calibration_automatic_precision
        >= minimum_automatic_precision
    )


def _json_safe(value: dict[str, Any]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, item in value.items():
        if item is None or isinstance(item, (str, int, float, bool)):
            safe[key] = item
        elif isinstance(item, tuple):
            safe[key] = list(item)
        else:
            safe[key] = repr(item)
    return safe


def _percentile(sorted_values: Sequence[float], quantile: float) -> float:
    if not sorted_values:
        raise ValueError("A percentile requires values.")
    index = min(len(sorted_values) - 1, math.ceil(len(sorted_values) * quantile) - 1)
    return sorted_values[index]
