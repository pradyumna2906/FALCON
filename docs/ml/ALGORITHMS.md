# Implemented algorithm locations for final review

| Component | Implemented technique | Main source |
|---|---|---|
| ETL | Validated canonical parsing, normalization, SHA-256 duplicate detection | `backend/src/falcon_api/imports/` |
| Classification features | Sanitized description/merchant tokens plus bounded transaction features | `classification/features.py` |
| Classification candidates | Word TF-IDF + logistic regression; word/character TF-IDF + LinearSVC, sigmoid calibration | `classification/training.py` |
| Classification orchestration | Rules → owner-confirmed merchant memory → calibrated model suggestion/abstention | `classification/hybrid.py` |
| Classification artifacts | Checksum/size/schema/library checks; cached lazy inference | `classification/artifacts.py` |
| Recurring analysis | Interval/amount consistency with explicit uncertainty | `analytics/recurring.py` |
| Spending signals | Rule-based leaks, duplicate-like entries, concentration, spikes and unusual amounts | `analytics/spending_signals.py` |
| Budgets and health | Exact-decimal variance/pace arithmetic and versioned weighted policy | `analytics/budgeting.py`, `analytics/health_score.py` |
| Forecast baselines | Last value, mean, median, moving average, seasonal naïve, drift | `forecasting/baselines.py` |
| Forecast ML | Recursive lag-feature CPU XGBoost regression | `forecasting/boosting.py` |
| Forecast statistics | ARIMA, SARIMA, optional Prophet | `forecasting/statistical.py` |
| Forecast evaluation | Rolling-origin validation, baseline improvement guard, final chronological test | `forecasting/evaluation.py`, `forecasting/selection.py` |
| Forecast uncertainty | Validation-residual interval calibration; provisional flag for scarce residuals | `forecasting/uncertainty.py` |
| Goal planning | Protected capacity, ranking, greedy baseline, HiGHS linear optimization and exact invariant checks | `goal_planning/` |
| Scenarios | Versioned hypothetical changes and comparisons without mutating baseline records | `scenario_simulation/` |
| Assistant | Owner-authorized evidence retrieval, ranked knowledge, evidence packets, provider generation and deterministic claim verification | `assistant/` |

Paths in the last column are relative to `backend/src/falcon_api/` unless given
in full. RAG is retrieval plus grounded generation; it does not imply that
FALCON trained the provider's language model. Anomaly, budget and health policies
are not separately trained ML estimators. LSTM and MiniLM are not introduced by
this batch. Supported models are compared, not all forced into every forecast.
