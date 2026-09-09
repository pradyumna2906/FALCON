# Phase 9 — Cognitive Financial Forecasting

Forecasting contract version: `2026.1`

This record is cumulative. It freezes the approved semantics and implementation
boundary for each completed Phase 9 checkpoint. Batch 1 contains Checkpoint 9.0,
Checkpoint 9.1, and Checkpoint 9.2. No model is trained, selected, persisted, or
served by an API in this batch.

## 1. Scope and ownership

Every forecasting read is derived from the authenticated principal. A client
cannot provide or override `user_id`, the trusted timezone, the data cutoff, a
model score, or a selected algorithm. Repository queries require the internal
principal identifier and join transactions to accounts using both owner and
account identifiers.

Phase 9 forecasts income, expense, cash flow, and a cash-flow savings proxy.
Phase 10 owns multi-goal ranking and allocation. A later Phase 9 checkpoint may
expose uncertainty evidence for goal feasibility, but it must not silently
perform Phase 10 optimization.

## 2. Checkpoint 9.0 — dependency and environment hardening

Runtime dependency `anyio==4.14.0` is pinned because the next unbounded release
currently makes Starlette's test-client deprecation warning fail FALCON's
warnings-as-errors test policy. The forecasting dependency group pins NumPy,
Pandas, scikit-learn, SciPy, Statsmodels, Joblib, Threadpoolctl, and XGBoost.
The normal development group contains the same modeling stack so CI and local
tests evaluate identical versions. FALCON uses the CPU-only XGBoost distribution
to avoid downloading unused GPU communication libraries in local and CI builds.

Prophet is isolated in the optional `forecasting-prophet` dependency group. It
will be installed only for its dedicated candidate adapter and compatibility
checks; absence of Prophet must never stop baseline, statistical, or XGBoost
forecasting.

## 3. Checkpoint 9.1 — target and metric semantics

Phase 9 inherits the exact Phase 8 cash-flow formulas instead of creating a
second financial vocabulary:

| Forecast target | Formula and included ledger data |
|---|---|
| Gross income | Sum of absolute amounts for posted income entries |
| Total expense | Sum of absolute amounts for posted expense entries |
| Net cash flow | Gross income minus total expense |
| Savings amount | Cash-flow proxy equal to net cash flow; not account balance, net worth, or investment performance |

Only `posted` external income and expense entries are eligible. `pending`
entries, internal transfers, and adjustments are excluded. Categorization is
not required for these total cash-flow targets. Archived accounts remain part
of historical observation because archiving an account must not rewrite a
user's financial history.

One series has exactly one ISO-style currency. Phase 9 performs no currency conversion
and never combines INR, USD, or another currency into one target.

Daily history may use up to 1,827 inclusive calendar days and forecast 1–366
future days. Monthly history must start on the first day of a month and end on
the last day of a month; it may forecast 1–24 future months. The minimum
normal-confidence threshold is three complete calendar months. The
quality policy for shorter or incomplete history belongs to Checkpoint 9.3.

## 4. Checkpoint 9.2 — leakage-safe source-series foundation

A `ForecastHistoryWindow` fixes the inclusive history start, history end,
trusted IANA timezone, daily or monthly granularity, and timezone-aware data
cutoff. The history cannot end after the cutoff's trusted local calendar date.
Monthly windows contain only complete calendar months.

The repository applies all of these predicates before aggregation:

- the authenticated owner matches `transactions.user_id`;
- the account owner and account identifier match the transaction;
- transaction dates fall inside the inclusive history window;
- both `created_at` and `updated_at` are at or before the data cutoff;
- the account currency matches the normalized requested currency;
- status is `posted`; and
- type is either external income or external expense.

The `created_at` and `updated_at` cutoff prevents rows created or changed after
the frozen dataset instant from entering an evaluation run. It does not invent
historical versions of mutable rows. Forecast persistence in Checkpoint 9.11
will retain the cutoff and provenance required to interpret a run.

PostgreSQL returns observed daily or monthly aggregates. The pure series
builder orders them chronologically, rejects duplicates or misaligned buckets,
and adds explicit zero-filled points for missing calendar periods. A zero-filled
point means no eligible ledger observation exists in that bucket; it does not
mean that the user proved they had no income or spending outside FALCON.

Money remains `Decimal` at four fractional places through source-series
construction. Model adapters may convert an immutable target vector to numeric
arrays later, but model output must be normalized back to the financial money
contract.

## 5. Deliberate Batch 1 exclusions

Batch 1 performs no history-quality scoring, chronological validation split,
feature generation, ARIMA/SARIMA fitting, Prophet fitting, XGBoost training,
model ranking, confidence-band calculation, forecast persistence, public API,
background job, notification, or goal optimization. Those responsibilities
remain with approved later checkpoints.

## 6. Batch 1 validation record

The 35 focused forecasting contract, period, repository, series, and
documentation tests passed. The complete backend unit suite passed 1,150 tests
with 95.17% combined statement and branch coverage, above the required 90%
gate, using Python 3.13.14 and the fully resolved pinned development stack.

All 39 PostgreSQL integration scenarios collect successfully. The new scenario
exercises owner isolation, currency isolation, pending-row exclusion, immutable
cutoff exclusion, archived-account history, exact aggregation, and source-series
construction against the real database when enabled. This review runner has no
Docker service, so live PostgreSQL execution, Compose validation, container
build, and smoke testing remain mandatory PR CI gates.

OpenAPI generation, Python compilation, offline Alembic upgrade and downgrade
SQL, dependency resolution, CPU-only XGBoost import, optional Prophet resolution,
canonical pre-commit hooks, whitespace validation, merge-marker checks, private
key detection, line-ending checks, case-conflict checks, and submodule checks
passed. Batch 1 adds no table or migration.

## 7. Checkpoint 9.3 — data quality and forecast eligibility

Quality policy version `2026.1` evaluates model-input evidence without claiming
model confidence. The assessment returns calendar period count, observed period
count, zero-filled period count and ratio, nonzero period count, transaction
count, robust outlier count and ratio, relative dispersion, eligibility, and
stable reason codes.

Eligibility has three explicit states:

- `unavailable`: the series contains no eligible transactions;
- `provisional`: some history exists but normal-history thresholds are not met;
  and
- `normal`: the frequency-specific history, observed-period, and transaction
  thresholds are met.

Monthly normal eligibility requires at least three calendar periods, three
observed periods, and six transactions. Daily normal eligibility requires at
least 90 calendar periods, 12 observed periods, and 20 transactions. Normal is
an input-data eligibility label, not a probability and not a guarantee that a
complex model will be reliable or selected.

More than 70% zero-filled calendar periods produces `sparse_activity` evidence.
Relative population standard deviation above the mean absolute value produces
`irregular_activity`. Robust outliers use the median absolute deviation with a
4.4478 × MAD threshold, equivalent to three robust standard deviations. The
outlier warning requires at least two outlying periods and at least 20% of the
series. Fewer than five points or a zero MAD produces no outlier claim because
the robust evidence is insufficient.

Irregular or outlier-heavy history is reported rather than deleted, winsorized,
or silently smoothed. Income and expense totals do not require transaction
classification coverage, consistent with the Phase 8 target semantics.

## 8. Checkpoint 9.4 — chronological evaluation framework

Evaluation policy version `2026.1` uses expanding-window rolling-origin
validation. The configuration fixes minimum training points, validation horizon,
step, final test size, and maximum validation folds. The latest bounded folds
are retained, and every validation range begins strictly after its training
range.

The final chronological test window is reserved and excluded from candidate
ranking. Candidate evaluation receives only each fold's earlier training values
and validation horizon; random shuffle and future-data leakage are prohibited.
The selected model's one-time test evaluation belongs to the later model-selection
checkpoint.

Every candidate uses one stable protocol: model code, minimum training points,
and a deterministic `predict(training_values, horizon)` operation. Invalid
horizons, insufficient training, mismatched prediction lengths, non-finite
values, overlapping test history, and series/plan mismatches fail closed.

Validation evidence records each fold's boundaries, actual values, predicted
values, and aggregate metrics:

- MAE: mean absolute error;
- RMSE: square root of mean squared error;
- WAPE: total absolute error divided by total absolute actual value; and
- bias: mean of `predicted - actual`, where positive means overforecasting.

Metrics use six-decimal half-even rounding. WAPE is null when every actual value
is zero, avoiding division-by-zero and invented accuracy.

## 9. Checkpoint 9.5 — transparent statistical baselines

The deterministic baseline registry contains:

| Baseline | Forecast behavior |
|---|---|
| Last value | Repeats the latest training value |
| Historical mean | Repeats the arithmetic mean of all training values |
| Historical median | Repeats the median of all training values |
| Moving average | Repeats the mean of the latest three values by default |
| Seasonal naïve | Repeats the latest complete 7-day or 12-month season |
| Drift | Extends the average first-to-last change per training step |

Baseline outputs return to the four-decimal money contract. Empty or non-finite
training data, invalid horizons, invalid windows, and insufficient seasonal
history are rejected. These candidates establish the minimum performance that
ARIMA/SARIMA, Prophet, and XGBoost must beat; a complex model is not preferred
merely because it is complex.

## 10. Batch 2 boundary

Checkpoints 9.3–9.5 add no database table, migration, public endpoint, model
artifact, ARIMA/SARIMA fit, Prophet fit, XGBoost fit, automatic model selection,
confidence band, goal probability, background job, or notification. The final
test window remains untouched until the later selection policy explicitly owns
its one-time use.

## 11. Batch 2 validation record

The complete unit suite passes on Python 3.13.14 with 1,185 tests and 95.34%
total coverage. The new quality, evaluation, and baseline modules each have
100% statement coverage. The focused Batch 2 and forecasting-contract run
passes 36 tests.

All 39 PostgreSQL integration scenarios collect, including the forecasting
source isolation scenario introduced in Batch 1. Live PostgreSQL execution was
not possible in this review runner because Docker is unavailable, so it remains
a mandatory PR CI gate.

Canonical pre-commit hooks, whitespace validation, Python compilation, OpenAPI
generation, and offline Alembic upgrade and downgrade SQL generation pass.
Batch 2 adds no schema migration or public API path.

## 12. Checkpoint 9.6 — leakage-safe feature engineering

Feature policy version `2026.1` converts an immutable target history into
chronological supervised rows. Every row is built only from values strictly
before its target index. The target value and all later validation or test
values are therefore unavailable to feature construction.

Daily candidates use lags 1, 7, 14, and 28 plus trailing 7- and 28-day mean
and population-standard-deviation features. Monthly candidates use lags 1, 2,
3, 6, and 12 plus trailing 3-, 6-, and 12-month mean and population-standard-
deviation features. Feature names, ordering, target indices, and policy version
are retained as auditable evidence.

Source money remains exact `Decimal`. Conversion to finite floating-point
values happens only at the model boundary. Empty, insufficient, non-finite, or
overflowing history fails closed. Features never interpolate, backfill, remove,
winsorize, or otherwise rewrite the calendar-complete source series.

## 13. Checkpoint 9.7 — statistical model candidates

ARIMA and SARIMA are bounded Statsmodels adapters implementing the same
candidate protocol as the transparent baselines. The default ARIMA order is
`(1, 1, 1)`. SARIMA uses order `(1, 1, 0)` and a deterministic seasonal order
of `(1, 0, 0, 7)` for daily series or `(1, 0, 0, 12)` for monthly series.
Candidate codes include the fixed family and frequency configuration.

The Prophet adapter is optional and imported only when that candidate is
executed. Missing Prophet produces an explicit unavailable-candidate result and
cannot prevent baseline, Statsmodels, or XGBoost execution. Prophet receives an
already bucketed, ordered series with synthetic monotonic daily or month-start
dates; it cannot query transactions or access future actual values.

All statistical adapters validate minimum history and positive horizons,
suppress library warnings at their boundary, convert only finite model outputs
back to four-decimal money, and translate dependency, fit, convergence, or
unsafe-output failures into stable fail-closed candidate errors. A failed
complex candidate never silently becomes a zero forecast.

## 14. Checkpoint 9.8 — deterministic CPU XGBoost candidate

The XGBoost candidate uses only the frozen Checkpoint 9.6 feature policy. The
CPU regressor has fixed squared-error objective, 64 estimators, maximum depth 3,
learning rate 0.05, full row and feature sampling, histogram trees, one worker,
and random seed 2026. These defaults bound resource use and make repeated fits
reproducible under the pinned environment.

Daily XGBoost requires 36 training points and monthly XGBoost requires 20,
providing eight supervised target rows beyond the largest lag. Multi-step
forecasts are recursive: each predicted value may become history for the next
step, but no future actual value is ever used. Missing CPU XGBoost, fit errors,
or non-finite predictions fail closed, and successful output returns to the
four-decimal financial money contract.

## 15. Batch 3 boundary

Checkpoints 9.6–9.8 provide candidate inputs and predictions only. They do not
rank candidates, choose a winner, read the reserved final test window, compute
confidence bands, estimate goal probability, persist an artifact or forecast,
add a database migration, expose a public endpoint, schedule a background job,
or send a notification. Automatic model selection remains owned by Checkpoint
9.9, uncertainty by Checkpoint 9.10, and persistence by Checkpoint 9.11.

## 16. Batch 3 validation record

The focused feature, statistical-candidate, XGBoost-candidate, and documentation
contract run passes 32 tests. The four new implementation modules have 99%
combined statement and branch coverage: feature construction, shared candidate
guards, and XGBoost each have 100%, while the statistical adapters have 97%.

The complete unit suite passes 1,215 tests with 95.44% total coverage. The
runner could not download the repository-standard Python 3.13.15 distribution
from its external release host, so this Batch 3 run used the available Python
3.12.14 interpreter with the exact pinned application and forecasting package
versions. Python 3.13.15 remains unchanged as the required PR CI runtime.

All 39 PostgreSQL integration scenarios collect. Python compilation, the
unchanged 33-path OpenAPI 3.1.0 document, offline Alembic upgrade and downgrade
SQL generation, canonical pre-commit hooks, and whitespace validation pass.
Live PostgreSQL and container execution remain mandatory PR CI gates because
Docker is unavailable in this runner. Batch 3 adds no database migration or
public API path.
