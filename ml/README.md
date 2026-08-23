# Machine Learning

This directory contains reusable forecasting, categorization, anomaly-detection, evaluation and explainability modules.

Models must use chronological validation where applicable, prevent data leakage, record evaluation results and communicate uncertainty. Real personal financial data must never be committed.

Phase 7 transaction classification uses the versioned taxonomy and contract in
[`docs/classification/PHASE_7_IMPLEMENTATION.md`](../docs/classification/PHASE_7_IMPLEMENTATION.md).
Training and production preprocessing must share one feature-schema version.
Artifacts must record their dataset version, evaluation split, library versions,
hyperparameters, checksum, calibration evidence, and abstention thresholds.

Feature schema `2026.1` is implemented in
`backend/src/falcon_api/classification/features.py`. It excludes exact amounts,
source-format identity, ownership, and source references from the primitive model
record. Sanitized descriptions and merchant candidates remain private data and
must not be emitted to ordinary logs or monitoring metrics.

Phase 7.4 implements dataset version `2026.1` and offline comparison in
`falcon_api.classification.dataset` and `falcon_api.classification.training`.
Install `backend[ml]`, then run from the repository root:

```text
PYTHONPATH=backend/src python scripts/build_classification_evidence.py
```

The command deterministically rebuilds the synthetic reference dataset,
integrity manifest, and `ml/reports/classification_evaluation_2026_1.json`.
It measures majority/rules baselines, TF-IDF logistic regression, and calibrated
Linear SVM without writing a serialized estimator. Synthetic evidence cannot
open the production deployment gate.
