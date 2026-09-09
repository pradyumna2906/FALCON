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

Phase 7.5 adds the dependency-light inference adapter, manifest/registry and
hybrid orchestration in `falcon_api.classification`. The separate packaging
command writes only to the ignored `ml/artifacts/classification` registry.
Ordinary API startup does not import scikit-learn, and a synthetic artifact is
restricted to suggestions even when its confidence exceeds the automatic
threshold.

Phase 9 forecasting uses the separately pinned `backend[forecasting]` dependency
group. Prophet remains isolated in `backend[forecasting-prophet]` so its
availability cannot block baseline, Statsmodels, or XGBoost candidates. Batch 1
defines target semantics and source-series construction only; it writes no model
or evaluation artifact.

Phase 9 Checkpoints 9.3–9.5 add deterministic history-quality evidence,
expanding-window rolling-origin validation with a final untouched test range,
MAE/RMSE/WAPE/bias calculations, and six transparent baselines. Random splits
are prohibited for financial time series. Later candidate models must outperform
eligible baselines under the same chronological evaluation policy.
