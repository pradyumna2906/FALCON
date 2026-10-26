"""Reproduce the validation-only experiment without replacing published evidence."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_review_models import load_inputs, save
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, f1_score, classification_report
from threadpoolctl import threadpool_limits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=Path("data/synthetic/review_2026_2")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "ml/reports/local_review_validation/validation_character_experiment.json"
        ),
    )
    args = parser.parse_args()
    if args.report.exists():
        parser.error(
            "Report already exists; preserve it and choose a new --report path."
        )
    root = args.data
    dataset, split = load_inputs(root)
    train = [r.model_text() for r in split.train]
    truth = [r.target for r in split.train]
    valid = [r.model_text() for r in split.calibration]
    vtruth = [r.target for r in split.calibration]
    rows = []
    with threadpool_limits(limits=1):
        for c in [0.5, 1.0, 4.0]:
            model = Pipeline(
                [
                    (
                        "tfidf",
                        FeatureUnion(
                            [
                                (
                                    "word",
                                    TfidfVectorizer(
                                        ngram_range=(1, 2),
                                        sublinear_tf=True,
                                        max_features=40000,
                                    ),
                                ),
                                (
                                    "character",
                                    TfidfVectorizer(
                                        analyzer="char_wb",
                                        ngram_range=(3, 5),
                                        min_df=3,
                                        sublinear_tf=True,
                                        max_features=60000,
                                    ),
                                ),
                            ]
                        ),
                    ),
                    (
                        "classifier",
                        CalibratedClassifierCV(
                            LinearSVC(
                                C=c, class_weight="balanced", random_state=20261004
                            ),
                            cv=3,
                            method="sigmoid",
                        ),
                    ),
                ]
            )
            t = time.perf_counter()
            model.fit(train, truth)
            pred = model.predict(valid)
            rows.append(
                {
                    "C": c,
                    "validation_accuracy": accuracy_score(vtruth, pred),
                    "validation_macro_f1": f1_score(vtruth, pred, average="macro"),
                    "seconds": time.perf_counter() - t,
                    "per_label": classification_report(
                        vtruth, pred, output_dict=True, zero_division=0
                    ),
                }
            )
            print(
                c,
                rows[-1]["validation_accuracy"],
                rows[-1]["validation_macro_f1"],
                flush=True,
            )
    save(
        args.report,
        {
            "partition": "validation_only",
            "final_test_accessed": False,
            "integrated": False,
            "experiments": rows,
        },
    )


if __name__ == "__main__":
    main()
