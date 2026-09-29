"""Tests for Phase 7.4 leakage-resistant model comparison and evidence."""

from datetime import date
from decimal import Decimal

import numpy as np
import pytest
from falcon_api.classification.dataset import (
    ClassificationDataset,
    DatasetSourceKind,
    LabeledFeatureSample,
    build_classification_dataset,
)
from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.classification.training import (
    CandidateName,
    compare_classification_models,
    group_stratified_split,
    select_confidence_thresholds,
)
from falcon_api.models.enums import TransactionType


_SECRET = b"classification-training-tests-use-a-private-secret"
_LABELS = (
    (
        ClassificationCategoryCode.FOOD_DINING,
        ClassificationSubcategoryCode.RESTAURANTS,
        TransactionType.EXPENSE,
        ("restaurant dinner", "cafe lunch"),
    ),
    (
        ClassificationCategoryCode.INCOME,
        ClassificationSubcategoryCode.SALARY,
        TransactionType.INCOME,
        ("monthly salary payroll", "employer wages income"),
    ),
    (
        ClassificationCategoryCode.INVESTMENT,
        ClassificationSubcategoryCode.MUTUAL_FUND,
        TransactionType.EXPENSE,
        ("mutual fund sip", "monthly equity fund investment"),
    ),
)


def _training_dataset(
    *,
    source_kind: DatasetSourceKind = DatasetSourceKind.SYNTHETIC,
    groups_per_label: int = 5,
) -> ClassificationDataset:
    samples: list[LabeledFeatureSample] = []
    for label_index, (category, subcategory, transaction_type, phrases) in enumerate(
        _LABELS
    ):
        for group_index in range(groups_per_label):
            merchant = f"Brand {chr(97 + label_index)}{chr(97 + group_index)}"
            for phrase_index, phrase in enumerate(phrases):
                amount = Decimal(500 + label_index * 100 + group_index * 10)
                if transaction_type is TransactionType.EXPENSE:
                    amount = -amount
                features = build_classification_features(
                    TransactionFeatureInput(
                        description=f"UPI {merchant} {phrase}",
                        merchant_name=merchant,
                        transaction_type=transaction_type,
                        signed_amount=amount,
                        transaction_date=date(2026, 1 + group_index, 10 + phrase_index),
                        account_currency="INR",
                    )
                )
                samples.append(
                    LabeledFeatureSample(
                        source_key=(
                            f"{subcategory.value}:{group_index}:{phrase_index}"
                        ),
                        group_key=f"{subcategory.value}:{group_index}",
                        features=features,
                        category=category,
                        subcategory=subcategory,
                        merchant_group=True,
                    )
                )
    return build_classification_dataset(
        samples,
        group_secret=_SECRET,
        source_kind=source_kind,
        dataset_version="test.1",
    )


def test_group_split_is_reproducible_stratified_and_group_isolated() -> None:
    dataset = _training_dataset()

    first = group_stratified_split(dataset, random_seed=42)
    second = group_stratified_split(dataset, random_seed=42)

    assert first == second
    assert len(first.train) == 18
    assert len(first.calibration) == 6
    assert len(first.test) == 6
    assert first.split_id.startswith("split_")
    train_groups = {record.group_id for record in first.train}
    calibration_groups = {record.group_id for record in first.calibration}
    test_groups = {record.group_id for record in first.test}
    assert train_groups.isdisjoint(calibration_groups | test_groups)
    assert calibration_groups.isdisjoint(test_groups)
    expected_labels = {item[1].value for item in _LABELS}
    assert {record.target for record in first.train} == expected_labels
    assert {record.target for record in first.calibration} == expected_labels
    assert {record.target for record in first.test} == expected_labels


def test_group_split_changes_identity_with_seed() -> None:
    dataset = _training_dataset(groups_per_label=6)

    assert (
        group_stratified_split(dataset, random_seed=1).split_id
        != group_stratified_split(dataset, random_seed=2).split_id
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"random_seed": -1},
        {"random_seed": 1.5},
        {"calibration_fraction": 0.0},
        {"calibration_fraction": 1},
        {"test_fraction": 0.5},
        {"calibration_fraction": 0.4, "test_fraction": 0.4},
    ],
)
def test_group_split_rejects_invalid_configuration(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        group_stratified_split(_training_dataset(), **kwargs)  # type: ignore[arg-type]


def test_group_split_requires_independent_groups_per_label() -> None:
    with pytest.raises(ValueError, match="independent groups"):
        group_stratified_split(_training_dataset(groups_per_label=2))


def test_group_split_rejects_a_group_with_multiple_labels() -> None:
    dataset = _training_dataset()
    records = list(dataset.records)
    restaurant = next(record for record in records if record.target == "restaurants")
    salary_index = next(
        index for index, record in enumerate(records) if record.target == "salary"
    )
    from dataclasses import replace

    records[salary_index] = replace(records[salary_index], group_id=restaurant.group_id)
    from falcon_api.classification.dataset import ClassificationDatasetManifest

    manifest = ClassificationDatasetManifest(
        dataset_version=dataset.manifest.dataset_version,
        source_kind=dataset.manifest.source_kind,
        feature_schema_version=dataset.manifest.feature_schema_version,
        taxonomy_version=dataset.manifest.taxonomy_version,
        record_count=len(records),
        group_count=dataset.manifest.group_count - 1,
        merchant_group_count=dataset.manifest.merchant_group_count,
        label_counts=dataset.manifest.label_counts,
        records_sha256="invalid",
    )
    # Bypass the dataset manifest guard to isolate the split invariant.
    dataset_with_mixed_group = object.__new__(ClassificationDataset)
    object.__setattr__(dataset_with_mixed_group, "records", tuple(records))
    object.__setattr__(dataset_with_mixed_group, "manifest", manifest)

    with pytest.raises(ValueError, match="multiple labels"):
        group_stratified_split(dataset_with_mixed_group)


def test_threshold_selection_maximizes_coverage_at_required_precision() -> None:
    truth = ["a", "a", "b", "b", "a", "b"]
    probabilities = np.asarray(
        [
            [0.95, 0.05],
            [0.80, 0.20],
            [0.10, 0.90],
            [0.30, 0.70],
            [0.45, 0.55],
            [0.60, 0.40],
        ]
    )

    thresholds = select_confidence_thresholds(
        truth,
        probabilities,
        ("a", "b"),
        minimum_automatic_precision=1.0,
        minimum_suggestion_precision=0.60,
    )

    assert 0.4 <= thresholds.automatic_confidence <= 1.0
    assert thresholds.suggestion_confidence <= thresholds.automatic_confidence
    assert thresholds.calibration_automatic_precision == 1.0
    assert thresholds.calibration_suggestion_precision is not None
    assert thresholds.calibration_suggestion_coverage >= (
        thresholds.calibration_automatic_coverage
    )


@pytest.mark.parametrize(
    ("truth", "probabilities", "classes", "error"),
    [
        ([], np.empty((0, 2)), ("a", "b"), ValueError),
        (["a"], [[1.0, 0.0]], ("a", "b"), TypeError),
        (["a"], np.asarray([1.0, 0.0]), ("a", "b"), TypeError),
        (["a"], np.asarray([[1.0]]), ("a", "b"), ValueError),
        (["a"], np.asarray([[0.5, -0.5]]), ("a", "b"), ValueError),
        (["a"], np.asarray([[0.4, 0.4]]), ("a", "b"), ValueError),
        (["a"], np.asarray([[1.0, 0.0]]), ("a", "a"), ValueError),
    ],
)
def test_threshold_selection_rejects_invalid_probability_evidence(
    truth: list[str],
    probabilities: object,
    classes: tuple[str, ...],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        select_confidence_thresholds(  # type: ignore[arg-type]
            truth, probabilities, classes
        )


def test_threshold_selection_rejects_invalid_precision_policy() -> None:
    probabilities = np.asarray([[0.8, 0.2], [0.2, 0.8]])
    with pytest.raises(ValueError):
        select_confidence_thresholds(
            ["a", "b"],
            probabilities,
            ("a", "b"),
            minimum_automatic_precision=1,
        )
    with pytest.raises(ValueError, match="Suggestion precision"):
        select_confidence_thresholds(
            ["a", "b"],
            probabilities,
            ("a", "b"),
            minimum_automatic_precision=0.8,
            minimum_suggestion_precision=0.9,
        )


def test_comparison_publishes_all_required_evidence_and_selects_learned_model() -> None:
    result = compare_classification_models(_training_dataset(), random_seed=17)
    report = result.report

    assert {evaluation.candidate for evaluation in report.evaluations} == set(
        CandidateName
    )
    assert report.selected_candidate in {
        CandidateName.TFIDF_LOGISTIC_REGRESSION,
        CandidateName.TFIDF_CALIBRATED_LINEAR_SVM,
    }
    assert result.selected_estimator.classes_.shape == (3,)
    assert report.selected_thresholds.automatic_confidence >= (
        report.selected_thresholds.suggestion_confidence
    )
    assert report.production_eligible is False
    assert report.dataset_source_kind is DatasetSourceKind.SYNTHETIC
    assert report.split_id.startswith("split_")
    assert set(report.library_versions) == {
        "python",
        "numpy",
        "scipy",
        "scikit_learn",
        "joblib",
    }
    assert len(report.deferred_candidates) == 2
    for evaluation in report.evaluations:
        assert 0 <= evaluation.macro_f1 <= 1
        assert 0 <= evaluation.weighted_f1 <= 1
        assert 0 <= evaluation.top_two_accuracy <= 1
        assert 0 <= evaluation.expected_calibration_error <= 1
        assert evaluation.artifact_size_bytes > 0
        assert len(evaluation.artifact_sha256) == 64
        assert evaluation.per_subcategory
        assert evaluation.per_category
        assert evaluation.confusion
        assert evaluation.unseen_merchant_macro_f1 is not None
    assert '"selected_candidate"' in report.to_json()
    assert "normalized_description" not in report.to_json()


def test_comparison_rejects_invalid_precision_targets() -> None:
    dataset = _training_dataset()
    with pytest.raises(ValueError):
        compare_classification_models(dataset, minimum_automatic_precision=0)
    with pytest.raises(ValueError, match="Suggestion precision"):
        compare_classification_models(
            dataset,
            minimum_automatic_precision=0.8,
            minimum_suggestion_precision=0.9,
        )
