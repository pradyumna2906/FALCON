"""Build and package the provisional Phase 7 classifier into the local registry.

Inputs: deterministic synthetic review data (or explicit legacy reference).
Outputs: ignored ``model.pkl`` and strict ``manifest.json`` below ml/artifacts.
Prerequisite: install the backend with its ``ml`` extra.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from pathlib import Path

from scripts.build_classification_evidence import build_reference_dataset
from scripts.build_review_datasets import build_review_classification
from falcon_api.classification.artifacts import package_model_comparison_result
from falcon_api.classification.training import compare_classification_models


DEFAULT_MODEL_VERSION = "classification_2026_3_review.1"


def main() -> None:
    """Rebuild, evaluate, and package one checksum-bound local artifact."""
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-version", default=DEFAULT_MODEL_VERSION)
    parser.add_argument("--dataset", choices=("review", "reference"), default="review")
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=repository_root / "ml" / "artifacts" / "classification",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace only the explicitly selected model version.",
    )
    arguments = parser.parse_args()

    if arguments.dataset == "review":
        dataset, split = build_review_classification()
        result = compare_classification_models(
            dataset, split=split, random_seed=split.random_seed
        )
    else:
        dataset = build_reference_dataset()
        result = compare_classification_models(dataset)
    manifest = package_model_comparison_result(
        result,
        registry_root=arguments.registry_root,
        model_version=arguments.model_version,
        overwrite=arguments.overwrite,
    )
    print(
        f"Packaged {manifest.model_version} ({manifest.candidate}); "
        f"production_eligible={manifest.production_eligible}."
    )


if __name__ == "__main__":
    main()
