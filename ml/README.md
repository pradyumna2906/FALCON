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
