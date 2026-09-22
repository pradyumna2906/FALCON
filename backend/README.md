# Backend

The FALCON backend is a FastAPI application organized as a layered modular monolith. It is authoritative for validation, financial calculations, persistence, authentication and authorization as those capabilities are introduced in later phases.

The current backend provides:

- A testable `create_app()` factory and Uvicorn entrypoint.
- Typed, immutable settings using `FALCON_` environment variables.
- One lazy async SQLAlchemy engine and session factory per application process.
- An explicit `/api/v1` compatibility boundary.
- A dependency-free `GET /health/live` operational endpoint.
- A bounded PostgreSQL-backed `GET /health/ready` readiness endpoint.
- Safe request correlation through `X-Request-ID`.
- An explicit, deny-by-default trusted browser-origin policy.
- Body-free structured JSON request logs written to standard output.
- One typed error envelope for validation, HTTP, application and unexpected errors.
- Automated API, configuration, database, request-context and error-contract tests.
- Reviewed PostgreSQL models and Alembic migrations for the current domains.
- Email/password authentication, session lifecycle, verification and recovery.
- An authenticated, user-isolated financial-profile API.
- Authenticated account provisioning and category discovery.
- User-isolated manual transaction and internal-transfer APIs.
- Authenticated, bounded CSV/XLSX/digital-PDF statement import and reconciliation APIs.
- A versioned Phase 7 transaction-classification taxonomy and strict confidence,
  abstention, provenance, batch-selection, and correction contracts.
- A versioned Phase 8 financial-analytics contract with exact metric, period,
  currency, completeness, confidence, and zero-data semantics, plus
  owner-scoped live PostgreSQL aggregation for summaries, trends, categories,
  merchants, accounts, recurring evidence, spending signals, budget variance,
  an explainable versioned financial-health score, and deterministic prioritized
  recommendations, with a consolidated dashboard export, fixed query budgets,
  live freshness, and privacy-safe aggregate monitoring.
- A versioned Phase 9 forecasting-target contract and owner-, currency-,
  history-, and cutoff-scoped daily/monthly source-series foundation.
- A versioned Phase 10 multi-goal planning foundation with exact progress,
  feasibility and ranking evidence, protected forecast capacity, constrained
  HiGHS allocation, financial guardrails, deterministic fallback, and auditable
  immutable plan versions with explicit approval history and authenticated APIs.
- A versioned Phase 11 scenario-simulation engine with deterministic shocks,
  seeded Monte Carlo risk, explainable comparison and sensitivity, immutable
  owner-scoped history, authenticated lifecycle APIs, and privacy-safe monitoring.

## Requirements

- Python 3.13.15.
- Docker Engine with Docker Compose for the real PostgreSQL integration test.
- A local `.env` copied from `.env.example` and kept out of Git.

Run all commands below from the repository root.

## Install

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -e "backend[dev]"
```

## Test

### Unit tests

```powershell
& .\.venv\Scripts\python.exe -m pytest backend\tests\unit
```

The unit command does not require PostgreSQL and enforces at least 90% statement and branch coverage for the current backend package.

### PostgreSQL integration test

Start the digest-pinned PostgreSQL service and explicitly enable the real integration test:

```powershell
docker compose --env-file .env up -d --wait postgres

$env:FALCON_RUN_DATABASE_INTEGRATION = '1'
try {
    & .\.venv\Scripts\python.exe -m pytest `
        backend\tests\integration `
        -m integration `
        --no-cov `
        --tb=short
}
finally {
    Remove-Item Env:\FALCON_RUN_DATABASE_INTEGRATION -ErrorAction SilentlyContinue
}
```

This suite uses the PostgreSQL address and credentials from `.env`. It runs the
production Psycopg async driver, migration lifecycle, public readiness route,
and application lifecycle tests. Tests create isolated records and remove
them when their lifecycle finishes. Run the suite only against a dedicated
development or test database. Stop the service when it is no longer needed
with `docker compose --env-file .env stop postgres`.

## Database migrations

FALCON uses Alembic as the only mechanism for creating or changing persistent
database schema. Application startup, tests and deployment code must never call
`metadata.create_all()`.

Alembic loads the PostgreSQL connection settings from the ignored root `.env`
file. Database credentials are never stored in `backend/alembic.ini`.

Inspect the current database revision:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    current
```

Upgrade to the latest reviewed migration:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    upgrade head
```

Downgrade one revision:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    downgrade -1
```

Generate a candidate migration after changing reviewed SQLAlchemy models:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    revision --autogenerate -m "describe schema change"
```

Every generated migration must be inspected before it is committed. Upgrade and
downgrade functions must be explicit and reversible whenever PostgreSQL permits.
Production deployments must run `upgrade head` as a separate controlled step,
not during API process startup.

The initial `25efb498276a` revision is intentionally empty. It establishes the
migration history before Phase 2.5 introduces domain tables.
## Run

```powershell
& .\.venv\Scripts\python.exe -m uvicorn falcon_api.main:app `
    --host 127.0.0.1 `
    --port 8000 `
    --loop falcon_api.core.event_loop:create_psycopg_compatible_event_loop `
    --reload
```

The explicit loop factory selects an asyncio selector loop. Psycopg async connections require this on Windows because they are incompatible with the default proactor loop; the same factory keeps integration tests and local API execution on one verified event-loop contract.

The current endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1` | Identifies the public API compatibility boundary |
| `GET` | `/health/live` | Confirms the API process is responsive without querying dependencies |
| `GET` | `/health/ready` | Confirms PostgreSQL can accept a bounded `SELECT 1` probe |
| `POST` | `/api/v1/auth/register` | Registers a user account |
| `POST` | `/api/v1/auth/login` | Issues an authenticated session |
| `POST` | `/api/v1/auth/refresh` | Rotates a refresh token |
| `POST` | `/api/v1/auth/logout` | Revokes the current refresh session |
| `POST` | `/api/v1/auth/email-verification/request` | Requests email verification |
| `POST` | `/api/v1/auth/email-verification/confirm` | Confirms email verification |
| `POST` | `/api/v1/auth/password-reset/request` | Requests password recovery |
| `POST` | `/api/v1/auth/password-reset/confirm` | Confirms a password reset |
| `GET` | `/api/v1/auth/me` | Returns the bearer-authenticated user |
| `GET` | `/api/v1/profile` | Returns the authenticated user's profile |
| `PUT` | `/api/v1/profile` | Creates or replaces the authenticated user's profile |
| `POST` | `/api/v1/accounts` | Provisions an account for transaction entry |
| `GET` | `/api/v1/accounts` | Lists the authenticated user's active accounts |
| `GET` | `/api/v1/categories` | Lists available system and private categories |
| `POST` | `/api/v1/transactions` | Creates a manual income or expense |
| `GET` | `/api/v1/transactions` | Lists the authenticated user's transactions |
| `GET` | `/api/v1/transactions/{transaction_id}` | Returns one owned transaction |
| `PUT` | `/api/v1/transactions/{transaction_id}` | Replaces an eligible manual transaction |
| `DELETE` | `/api/v1/transactions/{transaction_id}` | Deletes an eligible manual transaction |
| `POST` | `/api/v1/transfers` | Creates an atomic internal transfer |
| `POST` | `/api/v1/imports` | Imports one bounded CSV/XLSX/digital-PDF statement into an owned account |
| `GET` | `/api/v1/imports/{job_id}` | Returns one owned import reconciliation result |
| `GET` | `/api/v1/analytics/cash-flow` | Returns exact cash-flow metrics, trends, and prior-period values |
| `GET` | `/api/v1/analytics/spending` | Returns bounded category, merchant, and account expense distributions |
| `GET` | `/api/v1/analytics/recurring` | Returns explainable recurring patterns and explicit abstentions |
| `GET` | `/api/v1/analytics/spending-signals` | Returns explainable spending-leak and anomaly evidence |
| `GET` | `/api/v1/analytics/budgets/{budget_id}` | Returns budget variance and bounded overspend-risk evidence |
| `GET` | `/api/v1/analytics/health-score` | Returns a versioned explainable financial-health planning score |
| `GET` | `/api/v1/analytics/insights` | Returns bounded, deduplicated, prioritized financial review actions |
| `GET` | `/api/v1/analytics/dashboard` | Exports a five-query core dashboard bundle with shared summary semantics |
| `GET` | `/docs` | Development-only Swagger UI |
| `GET` | `/redoc` | Development-only ReDoc UI |
| `GET` | `/openapi.json` | Development-only OpenAPI document |

Production disables all documentation routes unless `FALCON_DOCS_ENABLED=true` is explicitly supplied. Production also rejects `FALCON_DEBUG=true`.

## Run with Docker Compose

Build and start the production-shaped API and PostgreSQL services:

```powershell
docker compose --env-file .env up --build --detach --wait api postgres
```

Verify both health contracts from the host:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Inspect logs and stop the services without deleting PostgreSQL data:

```powershell
docker compose --env-file .env logs --follow api
docker compose --env-file .env down
```

The default API container has no source bind mount and no reload process. It runs as UID/GID `10001`, publishes only to loopback, connects to PostgreSQL at `postgres:5432`, and uses dependency-free liveness for its Docker healthcheck. Readiness remains a separate PostgreSQL-backed contract.
## PostgreSQL lifecycle

FALCON creates one lazy async SQLAlchemy engine and one `async_sessionmaker` when each application process enters its lifespan. Engine creation does not open a database connection, so the API can start and continue serving `/health/live` while PostgreSQL is temporarily unavailable. Shutdown always disposes the engine and its connection pool.

Application code receives one `AsyncSession` per request or explicit unit of work. The session dependency never commits automatically, rolls back failed work and always closes the session. Explicit `transaction_scope()` boundaries own commit and rollback; services and repositories never hide commits.

The initial pool permits five persistent connections plus five overflow connections per API process. Pool checkout, recycling, driver connection and readiness timeouts are configured through the `FALCON_DB_*` settings in `.env.example`. `pool_pre_ping` checks reused connections before application work.

`GET /health/ready` bounds the entire connection-and-query operation and executes only `SELECT 1`. A timeout or database failure returns the common `503 service_unavailable` error envelope without exposing the database host, username, password, SQLAlchemy URL, query parameters or driver message. Database passwords use Pydantic `SecretStr`, and normal SQLAlchemy URL rendering redacts them.

## Browser access

FALCON authorizes browser origins only when they are listed exactly in the JSON-formatted `FALCON_CORS_ALLOWED_ORIGINS` setting:

```dotenv
FALCON_CORS_ALLOWED_ORIGINS=["http://localhost:5173","https://app.example.com"]
```

The setting defaults to an empty list, so browser cross-origin access is denied unless explicitly configured. Each entry must be a unique HTTP(S) origin containing only a scheme, host and optional non-default port. Wildcards, credentials, paths, query strings and fragments are rejected during startup.

The current policy permits `DELETE`, `GET`, `POST`, and `PUT` requests and the `Accept`,
`Authorization`, `Content-Type`, and `X-Request-ID` request headers. It exposes
`X-Request-ID` to trusted browser clients and permits credentialed requests
only for explicitly configured origins. Other methods and headers remain
denied until their owning capability requires and tests them.

An untrusted simple request is still processed by the API but receives no `Access-Control-Allow-Origin` response header, so the browser denies cross-origin access. A rejected preflight receives a CORS `400` response rather than an application authorization response.

## Request correlation and logging

Every HTTP response includes `X-Request-ID`. A client identifier is retained only when it is 1-64 characters, starts with an ASCII letter or digit and otherwise contains only ASCII letters, digits, `.`, `_`, `:` or `-`. Missing or malformed values are replaced with a generated identifier.

Request logs are emitted as one JSON object per line and contain only approved operational fields: request ID, method, normalized path, status, duration and exception type where applicable. Query strings, headers, cookies, request bodies and response bodies are not logged. FALCON disables Uvicorn's default access logger so this middleware remains the only access-log source and duplicate uncorrelated request lines are not emitted.

## Error responses

All framework and application errors use the same response shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found.",
    "request_id": "0198-example",
    "timestamp": "2026-08-11T12:00:00Z"
  }
}
```

Validation responses may additionally contain bounded field-level `details`. Rejected values, custom HTTP detail, stack traces and exception messages are never returned. Expected failures must raise `ApplicationError` with a stable snake-case code, a deliberately public message and an HTTP error status.

## Boundaries

- Do not place business rules in route handlers.
- Add capability modules only when their implementation phase begins.
- Never log or commit secrets, tokens, bank statements or real financial records.
- Never include private exception or dependency details in an `ApplicationError` message.
- Do not trust client-calculated financial values.


## Persistence and transaction boundaries

FALCON uses one process-owned asynchronous SQLAlchemy engine and one session
factory derived from that engine. The application lifecycle creates and
disposes the engine; feature code must not create separate connection pools.

Every database-backed operation uses one `AsyncSession` inside
`transaction_scope()`:

```python
async with transaction_scope(resources.session_factory) as session:
    await service_operation(session)
```

The boundary provides the following behaviour:

- successful work commits when the transaction context exits
- failed work rolls back before the exception propagates
- the session closes in every case
- objects remain available after commit because `expire_on_commit` is disabled
- autoflush is disabled, so feature code flushes deliberately when required

FastAPI request handlers receive their session through
`get_database_session()`. Routes, services, repositories, and SQLAlchemy models
must not:

- create independent engines or session factories
- open unrelated sessions inside one business operation
- call `commit()` implicitly
- hide transaction boundaries inside model methods
- call `metadata.create_all()` during startup, tests, CI, or production

SQLAlchemy relationships help Python code navigate models. PostgreSQL foreign
keys and constraints remain authoritative for persistent integrity.

The persistence foundation itself introduced no domain tables. Current domain
models were added later through reviewed Alembic migrations; future models
must follow the same migration-only workflow.

### Running persistence tests

Run the unit suite with the project Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\unit -q
```

The real PostgreSQL integration tests are explicitly enabled:

```powershell
$env:FALCON_RUN_DATABASE_INTEGRATION = '1'

.\.venv\Scripts\python.exe -m pytest `
    backend\tests\integration\test_postgresql_readiness.py `
    -m integration `
    --no-cov `
    -q
```

Clear the temporary environment setting afterward:

```powershell
Remove-Item Env:FALCON_RUN_DATABASE_INTEGRATION
```
## Authentication implementation

Phase 3 provides registration, email verification, login, refresh-token
rotation, replay revocation, logout, password recovery, bearer authentication,
and the authenticated `/api/v1/auth/me` endpoint.

The authoritative implementation and operational contract is documented in
[`docs/authentication/PHASE_3_IMPLEMENTATION.md`](../docs/authentication/PHASE_3_IMPLEMENTATION.md).

Run the complete backend suite from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest -q backend/tests
```

Run the real PostgreSQL authentication and database lifecycles:

```powershell
$env:FALCON_RUN_DATABASE_INTEGRATION = '1'
.venv\Scripts\python.exe -m pytest --no-cov -q backend/tests/integration
Remove-Item Env:FALCON_RUN_DATABASE_INTEGRATION
```

The private root `.env` must remain outside Git.

## Financial profile implementation

Phase 4 provides strict financial-profile validation, server-derived
completion state, user-scoped persistence, concurrent first-update recovery,
and authenticated `GET` and `PUT` operations at `/api/v1/profile`.

The authoritative contract and validation record is documented in
[`docs/financial-profile/PHASE_4_IMPLEMENTATION.md`](../docs/financial-profile/PHASE_4_IMPLEMENTATION.md).

## Transaction management implementation

Phase 5 provides account setup, category discovery, strict signed-ledger
semantics, user-scoped persistence, manual transaction lifecycle operations,
and atomic internal transfers.

The authoritative contract and checkpoint record is documented in
[`docs/transactions/PHASE_5_IMPLEMENTATION.md`](../docs/transactions/PHASE_5_IMPLEMENTATION.md).

## Statement import implementation

Phase 6 provides strict multipart upload metadata, secure bounded CSV/XLSX and
digital-PDF extraction, deterministic normalization and deduplication, atomic
ledger loading, persisted reconciliation issues, and owner-isolated
upload/status operations at `/api/v1/imports`.

Digital PDF statements use `source_type=bank_statement`. They may supply an
ephemeral `file_password`, are limited to 100 pages as well as the shared
10 MiB/10,000-row limits, and reject scanned, active-content, embedded-file, or
unsupported layouts. Successful jobs expose the selected adapter and, when a
complete running-balance column is present, its reconciliation result. PDF
passwords and raw statement bytes are never persisted or returned.

Raw statement bytes are processed only within the request and are not retained.
The authoritative contract and checkpoint record is documented in
[`docs/imports/PHASE_6_IMPLEMENTATION.md`](../docs/imports/PHASE_6_IMPLEMENTATION.md).

## Transaction classification implementation

Phase 7.1 defines taxonomy version `2026.1` and the strict ownership, prediction,
confidence, abstention, provenance, privacy, and user-correction boundaries for
the hybrid rules-and-ML classifier. Phase 7.2 adds the shared feature schema,
reference masking, merchant candidate extraction, payment-channel detection,
amount bands, calendar signals, and recurring-payment indicators. Trained
artifacts, persistence, and routes are introduced only by later checkpoints.
Phase 7.3 adds versioned, exact reviewed merchant knowledge and high-precision
keyword/channel rules with deterministic priority and explicit conflict
abstention. It does not use fuzzy merchant matching or user feedback memory.
Phase 7.4 adds the versioned privacy-bounded dataset workflow, opaque group-aware
train/calibration/test splitting, majority and rules baselines, TF-IDF logistic
regression and calibrated Linear SVM comparison, calibration-driven confidence
thresholds, and publishable evaluation evidence. The reference evidence is
synthetic and explicitly not production-eligible.
Phase 7.5 adds a stable classifier adapter, strict artifact manifest and local
packaging workflow, checksum/size/library compatibility verification, a
thread-safe lazy artifact provider, and rules-first hybrid orchestration.
Provisional synthetic models can suggest but never automatically assign a
category. Phase 7.6 adds stable system taxonomy-category mappings, owner-scoped
classification provenance, atomic automatic category assignment, protected
idempotence, and authenticated single and bounded-batch routes. Phase 7.7 adds
append-only correction snapshots, owner-isolated exact merchant memory,
memory-aware batch inference, and authenticated create/replace/list/delete
personalization operations without automatic global-model retraining. Phase 7.8
closes the phase with static reason-code explanations, aggregate privacy-safe
operational events, a guarded 100-item batch query shape, PostgreSQL index and
lifecycle validation, and full regression requirements. The committed synthetic
model remains provisional and cannot automatically assign model-only results.

The authoritative contract and checkpoint record is documented in
[`docs/classification/PHASE_7_IMPLEMENTATION.md`](../docs/classification/PHASE_7_IMPLEMENTATION.md).

## Financial analytics implementation

Phase 8.1 freezes versioned metric, date-window, currency, transaction-status,
classification-completeness, confidence, freshness, comparison, and zero-data
semantics. Phase 8.2 implements those meanings as exact, owner-scoped live
PostgreSQL aggregations for summary metrics, observed daily/monthly cash flow,
canonical categories, normalized merchants, and historical accounts. Every
surface uses one bounded SQL statement and archived ledger history remains
eligible. Phase 8.3 exposes authenticated cash-flow and expense-only spending
responses with trusted period/currency defaults, previous-period values,
completeness/freshness context, exact ratios, and bounded dimensions.
Phase 8.4 adds live recurrence intelligence for canonical salary, rent, EMI,
SIP, insurance, utilities, subscriptions, and repeated merchants. Phase 8.5
adds robust spending-leak and anomaly evidence; Phase 8.6 adds exact budget
variance and bounded pace risk; Phase 8.7 adds the seven-factor explainable
financial-health score. Phase 8.8 converts those existing signals into fixed,
deduplicated, prioritized review actions with severity, urgency, confidence,
reason codes, cautious impact semantics, and no investment advice or forecast.
Phase 8.9 closes the phase with an explicit live-only snapshot policy,
read-after-commit invalidation, fixed per-operation SQL budgets, privacy-safe
aggregate telemetry, a consolidated dashboard export, and maximum-range
performance and full-regression gates. Persistent snapshots and process caches
remain deferred until production measurements justify their invalidation cost.

The authoritative contract and checkpoint record is documented in
[`docs/analytics/PHASE_8_IMPLEMENTATION.md`](../docs/analytics/PHASE_8_IMPLEMENTATION.md).

## Cognitive forecasting implementation

Phase 9 Batch 1 pins the forecasting environment, inherits exact income,
expense, net-cash-flow, and savings-proxy meanings from Phase 8, and builds
calendar-complete daily or monthly source series. Every PostgreSQL read is
restricted by authenticated owner, account ownership, currency, history window,
posted external cash-flow types, and an immutable dataset cutoff. Missing
calendar buckets are represented explicitly without converting currencies or
inventing observations.

No forecasting model is trained or exposed by Batch 1. History-quality scoring,
chronological model evaluation, candidate models, selection, uncertainty,
persistence, and APIs remain assigned to later approved Phase 9 checkpoints.

Phase 9 Batch 2 adds explainable unavailable/provisional/normal data eligibility,
frequency-specific sufficiency thresholds, sparse/irregular/outlier evidence,
expanding-window rolling-origin validation with an untouched final test window,
exact MAE/RMSE/WAPE/bias metrics, and last-value, mean, median, moving-average,
seasonal-naïve, and drift baselines. It still does not train or select a complex
model or expose forecasting through the API.

Phase 9 Batch 3 adds versioned lag and trailing-window features, bounded ARIMA
and SARIMA candidates, a lazy optional Prophet adapter, and deterministic CPU
XGBoost with recursive multi-step prediction. Every candidate uses training
history only and fails closed on missing dependencies, insufficient evidence,
fit errors, or unsafe output. Candidate ranking, final-test use, uncertainty,
persistence, and APIs remain assigned to later checkpoints.

Phase 9 Batch 4 adds validation-only model ranking, a 5% improvement requirement
before a complex model may replace the best baseline, and one-time final-test
evaluation after selection. Validation residuals produce provisional/normal 80%
and 95% uncertainty bands. Immutable owner-scoped forecast runs and points retain
cutoff, model, policy, metric, and bounded privacy-safe evidence provenance.
Phase 9 closure adds `FinancialForecastService.generate()` to execute the full
owner-scoped pipeline and exposes authenticated create, recent-history, and
single-run APIs under `/api/v1/forecasts`. Privacy-safe monitoring records only
bounded operational metadata. Goal probability, goal optimization, scenarios,
AI explanations, scheduled retraining, and notifications remain deferred to
Phases 10–13.

The authoritative cumulative contract and checkpoint record is documented in
[`docs/forecasting/PHASE_9_IMPLEMENTATION.md`](../docs/forecasting/PHASE_9_IMPLEMENTATION.md).

## Multi-goal optimization implementation

Phase 10 Batch 1 establishes the versioned goal-planning boundary and exposes
authenticated create, list, get, partial-update, complete, and cancel operations
under `/api/v1/goals`. Every lookup is owner-scoped, mutations lock the active
goal before validating its lifecycle, client payloads cannot set ownership or
status, and terminal goals retain history without further mutation. The existing
goal schema is reused, so this batch adds no database migration.

Phase 10 Batch 2 adds allocation-safe manual, transaction-linked, and
opening-balance contributions; exact contribution-aware progress; a cutoff-safe
owner-scoped planning snapshot; and a conservative bridge from Phase 9 monthly
savings forecasts to protected, expected, and upside capacity. Goal ranking,
probability, optimization, and persisted approval history remain deferred.

Phase 10 Batch 3 adds per-goal feasibility probabilities and deadline-risk
evidence, a deterministic explainable 0–100 ranking policy, and a non-persistent
greedy reference allocator that consumes each month's protected 95% lower savings
capacity at most once. The SciPy/HiGHS constrained optimizer, persisted plans,
approval workflow, and public optimization API remain deferred.

Phase 10 Batch 4 adds the pinned SciPy/HiGHS constrained optimizer, exact
post-solver invariant verification, debt-evidence blocking, liquid-balance
protection, a hard emergency-fund reserve, and deterministic fallback. It returns
one pure monthly contribution schedule plus greedy-versus-optimized score,
funding, deadline, and guardrail-compliance evidence.

Phase 10 final Batch 5 adds migration `b3e8f6c2d715`, immutable owner-scoped plan
runs, outcomes, periods, allocations, and append-only lifecycle events. One
transactional service freezes a new snapshot, builds and verifies the plan, and
persists it without partial writes. Six authenticated operations under
`/api/v1/goal-plans` generate, list, retrieve, approve, reject, and regenerate
plans. Approval records a decision only—it does not move money or create a goal
contribution. Foreign plans remain indistinguishable from missing plans, clients
cannot override trusted evidence or policies, and monitoring emits only bounded
privacy-safe operational fields.

The authoritative cumulative contract and checkpoint record is documented in
[`docs/goals/PHASE_10_IMPLEMENTATION.md`](../docs/goals/PHASE_10_IMPLEMENTATION.md).

## Scenario simulation implementation

Phase 11 Batch 1 establishes scenario-simulation contract version `2026.1` and
the boundary between trusted facts and hypothetical user inputs. A draft request
may identify one owned Phase 10 plan and supply at most ten strictly bounded,
uniquely named alternatives. Supported assumptions cover percentage income and
expense changes, one-time or recurring expense adjustments, temporary income
interruptions, goal target/date/priority/contribution/pause changes, and an
emergency-fund target. Unknown or server-owned fields are rejected.

`ScenarioEvidenceService.build()` loads only a generated or approved plan through
its authenticated owner, freezes a new trusted cutoff, loads the exact referenced
monthly savings forecast through the same owner, and verifies every forecast
period and protected lower bound against the immutable Phase 10 schedule. When
percentage income or expense assumptions require a baseline, it also selects an
owner-, cutoff-, currency-, target-, and horizon-matched Phase 9 forecast; missing
supplemental evidence remains an explicit warning. Goal
and period evidence, policy versions, user hypotheses, warnings, and provenance
form a deterministic SHA-256 snapshot. The service is read-only and never changes
the source plan, forecast, goals, contributions, profile, budget, account, debt,
or transaction data.

Phase 11 Batch 2 adds deterministic protected, expected, and upside reference
paths plus user-defined paths. Its fixed shock chain applies income changes and
interruptions, expense inflation, one-time and recurring expenses, debt-payment
deltas, emergency-target changes, and per-goal contribution increases or pauses
with exact monthly reconciliation. Negative capacity is explicitly clipped,
missing required forecast evidence fails closed, and no hidden stress constants
are introduced.

Every available path is reevaluated through the Phase 10 feasibility, probability,
ranking, HiGHS allocation, emergency-reserve, exact invariant, and guarded
fallback policies. Results contain schedules, completion outcomes, shortfalls,
scores, reserve status, and exact differences from the source plan. The source
plan remains immutable. Batch 2 adds no persistence table or public endpoint;
Monte Carlo, risk metrics, history, APIs, and closure remain assigned to
Checkpoints 11.6–11.14.

Phase 11 Batch 3 adds owner-scoped uncertainty calibration from Phase 9's stored
validation-calibrated 80% and 95% bands, explicit normal/provisional/conservative
reliability, and a protected point-mass fallback when stochastic evidence is not
safe. A bounded NumPy PCG64 Monte Carlo engine runs 1,000 trials by default and at
most 10,000, records replay seeds and sample digests, uses common random numbers
across alternatives, and vectorizes Phase 10 ranking, deadline, contribution,
capacity, and emergency-reserve guardrails without repeated solver calls.

The risk reducer reports goal and deadline completion probabilities, reserve
coverage, raw negative-savings risk, constraint feasibility, expected shortfall,
capacity and shortfall P10/P50/P90, conditional completion-period percentiles,
90% tail shortfall, and a transparent 0–100 robustness score. Empirical Monte
Carlo and Phase 10 analytical probability methods remain distinctly labelled.
Batch 3 is still non-persistent and has no public scenario endpoint; comparison,
history, orchestration, APIs, monitoring, and closure remain for 11.9–11.14.

Phase 11 Batch 4 adds deterministic cross-scenario comparison, exact baseline
deltas, non-causal sensitivity attribution, multi-factor robustness scoring,
Pareto dominance, conservative tie-breaking, and bounded recommendation reason
codes. The decision graph is validated by canonical SHA-256 identities before it
can be stored.

Six owner-scoped PostgreSQL tables preserve immutable runs, normalized scenario
definitions, monthly paths, goal outcomes, comparisons, and append-only selection
events. Composite ownership keys prevent cross-owner references; exact-money,
probability, replay-seed, lifecycle, and generated-event rules are database
enforced. Raw Monte Carlo buffers and private source facts are not stored.

Phase 11 final Batch 5 adds `ScenarioSimulationService.simulate()` as the single
transactional snapshot-to-analysis-to-persistence path. Regeneration reconstructs
stored user assumptions, preserves the prior seed and trial count, and writes a
new immutable run. Selection and clearing use owner locks, compare-and-set state,
and append-only events. CPU work is moved off the async loop and protected by
bounded process concurrency, queue wait, and per-owner request rate.

Six bearer-authenticated operations under `/api/v1/scenario-simulations`
generate, list, retrieve, compare, select or clear, and regenerate simulations.
Strict schemas prevent clients from controlling owner, cutoff, evidence, trials,
seeds, algorithms, constraints, or policies. Full responses expose bounded
assumptions, risk percentiles, tail loss, schedules, comparisons, sensitivity,
rankings, replay provenance, warnings, and policy versions without user identity,
raw samples, or private financial rows. Privacy-safe telemetry emits only closed
aggregate bands and bounded reasons through the structured-log allowlist.

The cumulative contract and checkpoint record is documented in
[`docs/scenarios/PHASE_11_IMPLEMENTATION.md`](../docs/scenarios/PHASE_11_IMPLEMENTATION.md).

## Grounded assistant foundation

Phase 12 Batch 1 establishes assistant contract version `2026.1` without adding
an LLM provider, vector database, migration, or public endpoint. The assistant is
strictly an explanation layer: analytics, forecasting, goal planning, and scenario
simulation remain authoritative for every financial value.

Ten closed intents cover dashboard, health, spending, forecast, goal, scenario,
and curated education questions. Generated answers require bounded evidence
summaries and citations; missing evidence is unavailable rather than guessed, and
unsafe or unsupported requests receive a closed refusal. Public schemas accept
only a bounded question and exclude owner identity, evidence selection, prompts,
provider settings, secrets, and hidden reasoning.

Six closed evidence families use intent-based authorization. Analytics, forecast,
goal-progress, goal-plan, and scenario evidence require the authenticated owner;
only curated knowledge can be public. Per-source prompt allowlists recursively
reject identity, credentials, account and transaction identifiers, raw statements,
rows, samples, prompts, and chain-of-thought. The fixed threat model covers
cross-owner access, injection, exfiltration, ungrounded claims, prohibited actions,
unsafe advice, logging leakage, and raw-financial embedding.

ADR 0004 keeps exact private values in owner-scoped PostgreSQL retrieval and uses
PostgreSQL full-text search for the first curated knowledge index. `pgvector` is
optional only after measured retrieval improvement; MongoDB and a standalone
vector database are not introduced. The cumulative contract is documented in
[`docs/assistant/PHASE_12_IMPLEMENTATION.md`](../docs/assistant/PHASE_12_IMPLEMENTATION.md).

Phase 12 Batch 2 implements that retrieval boundary. Five private adapters reuse
the existing owner-scoped analytics, forecast, goal-progress, goal-plan, and
scenario paths and convert their results into immutable, allowlisted evidence
records with canonical SHA-256 identities. Missing or foreign resources yield no
evidence, and adapters never expose a database connection or financial write tool.

Curated public education is stored in two dedicated PostgreSQL tables as versioned
documents and immutable bounded chunks. Offline ingestion requires reviewed HTTPS
provenance and closed topics. PostgreSQL generated weighted `tsvector` columns and
a GIN index provide the retrieval baseline; deterministic lexical reranking uses
full-text score, overlap, title, heading, phrase, and topic signals. Retired or
future documents are excluded, queries are represented only by digests in
provenance, and no private financial data or embedding is indexed.

Phase 12 Batch 3 converts those records into immutable, replayable evidence
packets. Authenticated ownership is checked before the owner-free packet is built;
system rules, user text, metadata, and exact facts remain structurally separate.
Packets choose the latest unambiguous evidence, expose missing and stale sources,
enforce character/token budgets, and receive canonical SHA-256 identities.

The provider-neutral `AssistantModel` boundary is disabled until an approved
transport is configured. Its structured adapter allows no tools, enforces low
temperature, timeout, token, cost, retry, and response-size limits, and rejects
malformed JSON, hidden fields, duplicate keys, and evidence references outside the
packet. Grounding then verifies claim/source compatibility and exact numeric
support, constructs claim-level citations and reliability on the server, and fails
closed on guarantees, product instructions, money movement, or missing evidence.
Batch 3 adds no provider SDK, network configuration, conversation persistence, or
public assistant route.

Phase 12 Batch 4 adds encrypted owner-scoped conversation turns and append-only
content-free audit events through migration `e8c2a6d1f704`. Server code must
inject a configured Fernet key ring; no default or development encryption key is
provided. The first key encrypts new turns and older keys support rotation.
Conversations expire after 90 days, hold at most 50 turns, and can be erased by
owner or with a bounded retention job. User deletion cascades to the audit trail.
The job is scheduled only when deployment wiring is implemented.

Question and retrieved-text screening runs before generation. Final verification
checks claim-level source, numeric and unit support, citations, uncertainty, and
private-data leakage before an answer is eligible for persistence. An offline
labelled evaluation set measures retrieval precision/recall, citations,
faithfulness, safety refusals, leakage, and fixture operational budgets. Batch 4
does not add a public assistant endpoint or external model configuration.
