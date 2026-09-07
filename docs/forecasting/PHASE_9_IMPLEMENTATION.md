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
